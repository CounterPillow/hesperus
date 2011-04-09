import time
import urllib2
import json
from datetime import datetime
from time import time, sleep
from copy import copy
from posixpath import split as posix_split

from github.github import GitHub

from ..plugin import PollPlugin
from ..core import ET, ConfigurationError

# how each event is printed
DEFAULT_FORMATS = {
    'PushEvent' : "{actor} pushed {payload[size]} commit{payload[plural]} to {payload[ref]} at {repository[owner]}/{repository[name]} ({url})",
    'IssuesEvent' : "{actor} {payload[action]} issue #{payload[number]}: \"{payload[issue][title]}\" on {repository[owner]}/{repository[name]} ({url})",
    'CommitCommentEvent' : "{actor} commented on commit {payload[commit]} on {repository[owner]}/{repository[name]} ({url})",
    'GollumEvent' : "{actor} {payload[action]} \"{payload[title]}\" in the {repository[owner]}/{repository[name]} wiki ({url})",
    'CreateEvent' : "{actor} created {payload[object]} {payload[object_name]} at {repository[owner]}/{repository[name]} ({url})",
    'DeleteEvent' : "{actor} deleted {payload[ref_type]} {payload[ref]} at {repository[owner]}/{repository[name]} ({url})",
    'PullRequestEvent' : "{actor} {payload[action]} pull request {payload[number]}: \"{payload[pull_request][title]}\" on {repository[owner]}/{repository[name]} ({url})",
    'WatchEvent' : "{actor} {payload[action]} watching {repository[owner]}/{repository[name]} ({url})",
    'DownloadEvent' : "{actor} uploaded \"{payload[filename]}\" to {repository[owner]}/{repository[name]} ({url})",
}

# use url shortener
def _short_url(url):
    if not url:
        return None
    
    apiurl = 'https://www.googleapis.com/urlshortener/v1/url'
    data = json.dumps({'longUrl' : url})
    headers = {'Content-Type' : 'application/json'}
    r = urllib2.Request(apiurl, data, headers)
    
    try:
        retdata = urllib2.urlopen(r).read()
        retdata = json.loads(retdata)
        return retdata.get('id', url)
    except urllib2.URLError:
        return url
    except ValueError:
        return url

# make refs look nice
def _nice_ref(ref):
    if ref.startswith('refs/heads/'):
        return ref.split('/', 2)[2]
    return ref

# automatically spaces out github requests!
class AutoDelayGitHub:
    def __init__(self, delay=3.0):
        self.gh = GitHub()
        self.lasttime = 0
        self.delay = delay

    def __getattr__(self, name):
        while time() < self.lasttime + self.delay:
            sleep(self.lasttime + self.delay - time())
        self.lasttime = time()
        return getattr(self.gh, name)

class GitHubPlugin(PollPlugin):
    poll_interval = 50
    
    @PollPlugin.config_types(feedmap=ET.Element)
    def __init__(self, core, feedmap=None):
        super(GitHubPlugin, self).__init__(core)
        
        self.feedmap = {}
        self.events_cached = {}

        if feedmap == None:
            feedmap = []
        for el in feedmap:
            if not el.tag.lower() == 'feed':
                raise ConfigurationError('feedmap must contain feed tags')
            channel = el.get('channel', None)
            feed_url = el.text
            if not channel or not feed_url:
                raise ConfigurationError('invalid feed tag')
            
            if not feed_url in self.feedmap:
                self.feedmap[feed_url] = [channel]
                self.events_cached[feed_url] = []
            else:
                self.feedmap[feed_url].append(channel)
        
        self.gh = AutoDelayGitHub()
        
    def get_events(self, url):
        #self.log_debug("fetching", url)
        r = urllib2.Request(url)
        retdata = urllib2.urlopen(r).read()
        retdata = json.loads(retdata)
        # ex. "2011/03/22 00:49:44 -0700"
        timefmt = "%Y/%m/%d %H:%M:%S" # timezone is ignored, split off
        for event in retdata:
            event['created_at'] = event['created_at'].rsplit(' ', 1)[0]
            event['created_at'] = datetime.strptime(event['created_at'], timefmt)
        return retdata
        
    def postprocess_event(self, e):
        event = copy(e)
        if 'payload' in event:
            payload = event['payload']
            if 'ref' in payload:
                payload['ref'] = _nice_ref(payload['ref'])
            if 'size' in payload:
                payload['plural'] = ''
                if payload['size'] != 1:
                    payload['plural'] = 's'
                if 'commit' in payload:
                    payload['commit'] = payload['commit'][:6]
        if event['type'] == 'IssuesEvent':
            payload = event['payload']
            issue = self.gh.issues.show(event['repository']['owner'], event['repository']['name'], payload['number'])
            payload['issue'] = issue.__dict__
        if event['type'] == 'DownloadEvent':
            payload = event['payload']
            payload['filename'] = posix_split(payload['url'])[1]
            event['url'] = payload['url']
        if 'url' in event:
            event['url'] = _short_url(event['url'])
        return event
    
    def start(self):
        # fetch the initial cache of events
        for url in self.feedmap:
            self.events_cached[url] = self.get_events(url)
        
        super(GitHubPlugin, self).start()
    
    def poll(self):
        for feed in self.feedmap:
            try:
                events_new = self.get_events(feed)
            except urllib2.HTTPError:
                # try again later
                self.log_warning("fetch failed:", feed)
                return
            yield
            
            channels = self.feedmap[feed]
            old = self.events_cached[feed]
            if len(old) > 0:
                last_update = old[0]['created_at']
                new = filter(lambda x: x['created_at'] > last_update, events_new)
            else:
                new = events_new
            yield
            
            for e in new:
                event = self.postprocess_event(e)
                
                if not event['type'] in DEFAULT_FORMATS:
                    self.log_warning("unhandled event", event['type'])
                else:
                    msg = DEFAULT_FORMATS[event['type']]
                    msg = msg.format(**event)
                    self.log_message(msg)
                    for chan in self.feedmap[feed]:
                        self.parent.send_outgoing(chan, msg)
                
                yield
            
            self.events_cached[feed] = events_new