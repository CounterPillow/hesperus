import gearman
from hesperus.plugin import CommandPlugin
import re

class GearmanStatusPlugin(CommandPlugin):
    @CommandPlugin.config_types(gearman_host=str)
    def __init__(self, core, gearman_host):
        super(GearmanStatusPlugin, self).__init__(core)
        self.admin_client = gearman.GearmanAdminClient([gearman_host])

    @CommandPlugin.register_command(r"jobs(?:\s+(.*))?")
    def job_status_command(self, chans, name, match, direct, reply):
        running = []
        idle = []
        if match.group(1):
            fltr = lambda t: re.search(match.group(1), t['task'])
        else:
            fltr = lambda t: True
        try:
            for task in self.admin_client.get_status():
                if fltr(task):
                    if task['running'] == 0 and task['queued'] == 0:
                        idle.append(task['task'])
                    else:
                        running.append('%s: %d+%d/%d' % (task['task'], task['running'], task['queued'], task['workers']))
        except gearman.errors.ServerUnavailable:
            reply('I\'m sorry, but the number you have dialed has been disconnected or is no longer in service.')
        except gearman.errors.InvalidAdminClientState:
            reply('I let it ring but no one answered :(')
        else:
            if idle:
                reply('Idle tasks: ' + ', '.join(idle))
            for task in running:
                reply(task)
    
    @CommandPlugin.register_command(r"workers(?:\s+(.*))?")
    def worker_status_command(self, chans, name, match, direct, reply):
        workers_found = False
        if match.group(1):
            fltr = lambda w: any(map(lambda t: re.search(match.group(1), t), w['tasks']))
        else:
            fltr = lambda w: True
        try:
            for worker in self.admin_client.get_workers():
                #admin client's client_id is '-'
                if worker['client_id'] != '-' and fltr(worker):
                    workers_found = True
                    reply('%s[%s]: %s' % (worker['client_id'], worker['ip'], ', '.join(worker['tasks'])))
            if not workers_found:
                reply('No workers found :(')
        except gearman.errors.ServerUnavailable:
            reply('I\'m sorry, but the number you have dialed has been disconnected or is no longer in service.')
        except gearman.errors.InvalidAdminClientState:
            reply('I let it ring but no one answered :(')
                
