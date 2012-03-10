import sys
import os
import re
import datetime
import time
import optparse
import boto.ec2
import socket
import itertools
from IPython.core.error import UsageError
import ConfigParser

class Account(object):
    def __init__(self, name, access_key, secret_key, default_regions):
        self.name = name
        self.access_key = access_key
        self.secret_key = secret_key
        self.default_regions = default_regions
        
    @classmethod
    def default(cls):
        if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
            return Account('default', os.getenv('AWS_ACCESS_KEY_ID'), os.getenv('AWS_SECRET_ACCESS_KEY'), os.getenv('EC2_REGION'))
        return 

class Connection(object):
    def __init__(self, acc, reg):
        self.account = acc
        self.region = reg
        self._ec2 = None
        
    def instances(self):
        return iter_instances(self.ec2.get_all_instances())
        
    @property    
    def ec2(self):
        if not self._ec2:
            self._ec2 = boto.ec2.connect_to_region(self.region,
                                              aws_access_key_id = self.account.access_key,
                                              aws_secret_access_key = self.account.secret_key,
                                              )
        return self._ec2
        
    def __str__(self):
        return '%s:%s' % (self.account.name, self.region)
        
class ConnectionList(list):
    def __str__(self):
        return ','.join( str(c) for c in self )

    def instances(self):
        for c in self:
            for i in c.instances():
                yield i
        
    @property
    def type(self):
        return 'connection'

class Context(object):
    def __init__(self, accounts):
        self.accounts = accounts
        self.filters = []
        
    def select_all(self):
        self.filters = [ ConnectionList( Connection(acc, reg) for acc in self.accounts for reg in acc.default_regions ) ]
        
    def select_account(self, name):
        for acc in self.accounts:
            if acc.name == name:
                self.filters = [ ConnectionList( Connection(acc, reg) for reg in acc.default_regions ) ]
                break
            
    def select_regions(self, names):
        filter = []
        accounts = set(conn.account for conn in self.filters[0] )
        filter = ConnectionList( Connection(acc, reg) for acc in accounts for reg in names )
        self.filters[0] = filter
        
    def add_filter(self, f):
        for i, x in enumerate(self.filters):
            if x.type == f.type:
                self.filters[i] = f
                return
        self.filters.append(f)
        
    def pop_filter(self):
        if len(self.filters) > 1:
            self.filters.pop()
        
    def instances(self, post_filter=None):
        filters = self.filters + (post_filter or [])
        res = None
        for f in filters:
            if not res:
                res = self.filters[0].instances()
            else:
                res = f.filter(res)
        return res
    
    def connections(self):
        return self.filters[0]
        
    def __str__(self):
        return ' '.join( str(f) for f in self.filters )

    @classmethod
    def configure(cls):
        iboto_cfg = os.path.join(os.getenv('HOME'), '.iboto')
        if os.path.exists(iboto_cfg):
            cfg = ConfigParser.RawConfigParser()
            cfg.read(iboto_cfg)
            accs = []
            for section in cfg.sections():
                access_key = cfg.get(section, 'aws_access_key_id')
                secret_key = cfg.get(section, 'aws_secret_access_key')
                regions = cfg.get(section, 'regions').split(',')
                acc = Account(section, access_key, secret_key, regions)
                accs.append(acc)
            return Context(accs)
        else:
            return Context([Account.default()])
            
    def command_line(self):
        args = sys.argv[1:]
        if len(args) > 0:
            self.select_account(args[0])
            if len(args) > 1:
                self.select_regions([args[1]])
        else:
            self.select_all()

class Instances(object):
    def __init__(self, ctx):
        self.ctx = ctx
        
    def start(self):
        self._on_all('start')
        
    def stop(self):
        self._on_all('stop')
        
    def _on_all(self, cmd):
        for i in self.ctx.instances():
            getattr(i, cmd)()
            
    @property
    def list(self):
        print 'blah'
        
    def __len__(self):
        return len(list(self.ctx.instances()))
        
    def __str__(self):
        return ', '.join( i.id for i in self.ctx.instances() )
        
    def __repr__(self):
        return 'Instances(limit=%s)' % str(self.ctx)

def load_ipython_extension(ipython):
    global ip
    ip = ipython

    ip.define_magic('ec2ssh', ec2ssh)
    ip.define_magic('ec2din', ec2din)
    ip.define_magic('ec2run', ec2run)
    ip.define_magic('ec2watch', ec2watch)

    ip.define_magic('account', magic_account)
    ip.define_magic('region', magic_region)
    ip.define_magic('limit', magic_limit)
    ip.define_magic('.', magic_limit)
    ip.define_magic('pop', magic_pop)

    _define_ec2cmd(ip, 'ec2start', 'start', 'stopped')
    _define_ec2cmd(ip, 'ec2stop', 'stop', 'running')

    _define_ec2cmd(ip, 'ec2kill', 'terminate', None)
    
    ip.set_hook('complete_command', instance_completer_factory(), re_key = '%?ec2din')
    ip.set_hook('complete_command', instance_completer_factory(), re_key = '%?ec2watch')
    ip.set_hook('complete_command', ec2run_completers, re_key = '%?ec2run')
    ip.set_hook('complete_command', ec2run_completers, re_key = '%?ec2-run-instances')
    ip.set_hook('complete_command',
                instance_completer_factory(filters={'instance-state-name': 'running'}),
                re_key = '%?ec2ssh')
    ip.set_hook('complete_command', account_completers, re_key = '%?account')
    ip.set_hook('complete_command', region_completers, re_key = '%?region')
    ip.set_hook('complete_command', instance_completer_factory(), re_key = r'%?(limit|\.)')
    
    global ctx
    ctx = Context.configure()
    ctx.command_line()
    ip.user_ns['ctx'] = ctx
    ip.user_ns['i'] = Instances(ctx)

# TODO better exception handling in completers
# TODO handle spaces in tags (completion)
# TODO autogenerate ec2run docstring

######################################################
# Helper functions
######################################################

re_allowed_chars = re.compile(r'[^a-z0-9_]+')
def to_slug(n):
    n = n.lower()
    n = re_allowed_chars.sub('_', n)
    return n

def iter_instances(reservations):
    for r in reservations:
        for i in r.instances:
            yield i
    
def list_instances(reservations):
    return list(iter_instances(reservations))

def firstinstance(reservations):
    for r in reservations:
        for i in r.instances:
            return i
    return None

def build_ami_list():
    # AMI list
    ami = dict()
    for fname in os.listdir('ami'):
        fname = os.path.join('ami', fname)
        cfg = ConfigParser.ConfigParser()
        cfg.read(fname)
        s = str(ec2.region.name)
        if cfg.has_section(s):
            for o in cfg.options(s):
                ami[o] = cfg.get(s, o)

    # Add custom AMIs
    for img in ec2.get_all_images(owners=[owner_id]):
        n = img.location.split('/')[-1]
        n = re.sub(r'\.manifest\.xml$', '', n)
        n = to_slug(n)
        ami[n] = str(img.id)
    
    return ami
# disabled for now
#ami = build_ami_list()

######################################################
# magic ec2run
######################################################

def resolve_ami(arg):
    amiid = None
    if arg.startswith('ami-'):
        amiid = arg
    elif arg in ami:
        amiid = ami[arg]
    return amiid

class enumeration(object):
    def __init__(self, values, multivalued=False):
        self.values = values
        self.multivalued = multivalued
        
    def __call__(self, x):
        if self.multivalued:
            values = x.split(',')
            for x in values:
                if x not in self.values:
                    raise ValueError, 'not a valid value'
            return values
        else:
            if x not in self.values:
                raise ValueError, 'not a valid value'
        return x
    
    def __str__(self):
        return ','.join(self.values)

class _instance_count(object):
    def __call__(self, x):
        if x is None:
            raise ValueError
        if '-' in x:
            a,b = x.split('-')
            return (int(a), int(b))
        else:
            a = int(x)
            return (a, a)
        
    def __str__(self):
        return 'n or n-m'
instance_count = _instance_count()

def prompt(p, validate=None, default=None):
    while True:
        value = raw_input(p)
        if default is not None and value == '':
            if validate:
                return validate(default)
            else:
                return default
        if validate:
            try:
                return validate(value)
            except ValueError, ex:
                print str(ex)

class CustomOptionParser(optparse.OptionParser):
    def exit(self, status=0, msg=''):
        raise ValueError, msg

ec2run_parser = CustomOptionParser(prog='%ec2run', usage='%prog [options] AMI')
ec2run_parser.add_option('-k', '--key', metavar='KEYPAIR', help='Specifies the key pair to use when launching the instance(s).')
ec2run_parser.add_option('-t', '--instance-type', metavar='TYPE', help='Specifies the type of instance to be launched.')
ec2run_parser.add_option('-n', '--instance-count', metavar='MIN-MAX', help='The number of instances to attempt to launch.')
ec2run_parser.add_option('-g', '--group', metavar='GROUP', action='append', help='Specifies the security group.')
ec2run_parser.add_option('-d', '--user-data', metavar='DATA', help='Specifies the user data to be made available to the instance(s) in this reservation.')
ec2run_parser.add_option('-f', '--user-data-file', metavar='DATA-FILE', help='Specifies the file containing user data to be made available to the instance(s) in this reservation.')
ec2run_parser.add_option('-m', '--monitor', action='store_true', help='Enables monitoring of the specified instance(s).')
ec2run_parser.add_option('-z', '--availability-zone', metavar='ZONE', help='Specifies the availability zone to launch the instance(s) in.')
ec2run_parser.add_option('--disable-api-termination', action='store_true', help='Indicates that the instance(s) may not be terminated using the TerminateInstances API call.')
ec2run_parser.add_option('--instance-initiated-shutdown-behavior', metavar='BEHAVIOR', help='Indicates what the instance(s) should do if an on instance shutdown is issued.')
ec2run_parser.add_option('--placement-group', metavar='GROUP_NAME', help='Specifies the placement group into which the instances should be launched.')
ec2run_parser.add_option('--private-ip-address', metavar='IP_ADDRESS', help='Specifies the private IP address to use when launching an Amazon VPC instance.')
ec2run_parser.add_option('--kernel', metavar='KERNEL', help='Specifies the ID of the kernel to launch the instance(s) with.')
ec2run_parser.add_option('--ramdisk', metavar='RAMDISK', help='Specifies the ID of the ramdisk to launch the instance(s) with.')
ec2run_parser.add_option('--subnet', metavar='SUBNET', help='The ID of the Amazon VPC subnet in which to launch the instance(s).')
# TODO block device mapping, client-token, addressing

ec2run_parameters = []
for o in ec2run_parser.option_list:
    ec2run_parameters.extend(o._short_opts + o._long_opts)
    
def parse_option(opts, message, validate, value, default=None):
    if value:
        try:
            return validate(value)
        except ValueError:
            pass

    if not isinstance(validate, type):
        message = '%s (%s)' % (message, validate)
    if default is not None:
        message = '%s [%s]' % (message, default)
    return prompt(message + ': ', validate=validate, default=default)

def ec2run(self, parameter_s):
    """Launch a number of instances of the specified AMI.

    Usage:\\
      %ec2run [options] AMI
      Almost all the options from the Amazon command line tool are supported:
      
     -d, --user-data DATA
          Specifies the user data to be made available to the instance(s) in
          this reservation.

     -f, --user-data-file DATA-FILE
          Specifies the file containing user data to be made available to the
          instance(s) in this reservation.

     -g, --group GROUP [--group GROUP...]
          Specifies the security group (or groups if specified multiple times)
          within which the instance(s) should be run. Determines the ingress
          firewall rules that will be applied to the launched instances.
          Defaults to the user's default group if not supplied.

     -k, --key KEYPAIR
          Specifies the key pair to use when launching the instance(s).

     -m, --monitor
          Enables monitoring of the specified instance(s).

     -n, --instance-count MIN[-MAX]
          The number of instances to attempt to launch. May be specified as a
          single integer or as a range (min-max). This specifies the minumum
          and maximum number of instances to attempt to launch. If a single
          integer is specified min and max are both set to that value.

     -s, --subnet SUBNET
          The ID of the Amazon VPC subnet in which to launch the instance(s).

     -t, --instance-type TYPE
          Specifies the type of instance to be launched. Refer to the latest
          Developer's Guide for valid values.

     -z, --availability-zone ZONE
          Specifies the availability zone to launch the instance(s) in. Run the
          'ec2-describe-availability-zones' command for a list of values, and
          see the latest Developer's Guide for their meanings.

     --disable-api-termination
          Indicates that the instance(s) may not be terminated using the
          TerminateInstances API call.

     --instance-initiated-shutdown-behavior BEHAVIOR
          Indicates what the instance(s) should do if an on instance shutdown
          is issued. The following values are supported
          
           - 'stop': indicates that the instance should move into the stopped
              state and remain available to be restarted.
          
           - 'terminate': indicates that the instance should move into the
              terminated state.

     --kernel KERNEL
          Specifies the ID of the kernel to launch the instance(s) with.

     --ramdisk RAMDISK
          Specifies the ID of the ramdisk to launch the instance(s) with.

     --placement-group GROUP_NAME
          Specifies the placement group into which the instances 
          should be launched.

     --private-ip-address IP_ADDRESS
          Specifies the private IP address to use when launching an 
          Amazon VPC instance.
    """
    try:
        opts,args = ec2run_parser.parse_args(parameter_s.split())
    except Exception, ex:
        raise UsageError, str(ex)
        return

    if not args:
        raise UsageError, '%ec2run needs an AMI specifying'
        return

    global ctx
    connections = ctx.connections()
    if len(connections) > 1:
        names = set(c.account.name for c in connections)
        if len(names) > 1:
            name = prompt('account (%s): ' % (', '.join(names)), enumeration(names))
            connections = [ c for c in connections if c.account.name == name ]
        regions = set(c.region for c in connections )
        if len(regions) > 1:
            region = prompt('region (%s): ' % (', '.join(regions)), enumeration(regions))
        connections = [ c for c in connections if c.region == region ]
    
    connection = connections[0]
    run_args = {}
    run_args['instance_type'] = parse_option(opts, 'size', enumeration(SIZES), opts.instance_type)
    run_args['key_name'] = parse_option(opts, 'key', str, opts.key)
    a, b = parse_option(opts, 'no. instances', instance_count, opts.instance_count, default='1')
    run_args['min_count'] = a
    run_args['max_count'] = b
    
    groups = [g.name for g in connection.ec2.get_all_security_groups()]
    run_args['security_groups'] = parse_option(opts, 'security group', enumeration(groups, multivalued=True), opts.group, default='default')

    zones = [z.name for z in connection.ec2.get_all_zones()]
    run_args['placement'] = parse_option(opts, 'availability zone', enumeration(zones), opts.availability_zone, default=zones[0])

    if opts.user_data:
        run_args['user_data'] = opts.user_data
    elif opts.user_data_file:
        run_args['user_data'] = file(opts.user_data_file, 'r')
    if opts.monitor:
        run_args['monitoring_enabled'] = True
    if opts.disable_api_termination:
        run_args['disable_api_termination'] = opts.disable_api_termination
    if opts.instance_initiated_shutdown_behavior:
        run_args['instance_initiated_shutdown_behavior'] = opts.instance_initiated_shutdown_behavior
    if opts.placement_group:
        run_args['placement_group'] = opts.placement_group
    if opts.private_ip_address:
        run_args['private_ip_address'] = opts.private_ip_address
    if opts.kernel:
        run_args['kernel_id'] = opts.kernel
    if opts.ramdisk:
        run_args['ramdisk_id'] = opts.ramdisk
    if opts.subnet:
        run_args['subnet_id'] = opts.subnet
    
    run_args['image_id'] = resolve_ami(args[0])
    r = connection.ec2.run_instances(**run_args)
    
    inst = firstinstance([r])
    return str(inst.id)

def ec2run_completers(self, event):
    cmd_param = event.line.split()
    if event.line.endswith(' '):
        cmd_param.append('')
    arg = cmd_param.pop()
    
    arg = cmd_param.pop()
    if arg in ('-t', '--instance-type'):
        return SIZES
    elif arg in ('-k', '--keys'):
        return [k.name for k in ec2.get_all_key_pairs()]
    elif arg in ('-n', '--instance-count'):
        return ['1', '1-'] # just examples really
    elif arg in ('-g', '--group'):
        return [g.name for g in ec2.get_all_security_groups()]
    elif arg in ('-d', '--user-data'):
        return []
    elif arg in ('-f', '--user-data-file'):
        return [] # TODO hook normal file complete
    elif arg in ('-z', '--availability-zone'):
        return [z.name for z in ec2.get_all_zones()]
    elif arg in ('--instance-initiated-shutdown-behavior'):
        return ['stop', 'terminate']
    elif arg in ('--placement-group'):
        return [g.name for g in ec2.get_all_placement_groups()]
    elif arg in ('--private-ip-address'):
        return []
    elif arg in ('--kernel'):
        return [] # TODO
    elif arg in ('--ramdisk'):
        return [] # TODO
    elif arg in ('--subnet'):
        return [] # TODO
    else:
        params = ec2run_parameters[:]
        # drop from params any already used
        for c in cmd_param:
            o = ec2run_parser.get_option(c)
            if o:
                for v in o._short_opts + o._long_opts:
                    if v in params: params.remove(v)
        return params + ami.keys()

def args_instances(parameter_s, filters=None):
    if not filters:
        filters = []
    if parameter_s:
        filters = filters + parse_filter_list(parameter_s)
    
    instances = ctx.instances(filters)
    if not instances:
        raise UsageError, 'No instances found'

    return instances

######################################################
# magic ec2ssh
######################################################

re_user = re.compile('^(\w+@)')

def ssh_live(ip, port=22):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((ip, port))
        s.shutdown(2)
        return True
    except:
        return False

def ec2ssh(self, parameter_s):
    """SSH to a running instance.

    Usage:\\
      %ec2ssh [-i ...] [user@]i-xxxxxxx|Tag:Value|latest
      
    Extra parameters (-i, etc.) will be sent through verbatim to ssh.

    The last parameter is expanded into the public host name for the first 
    instance matched. The instance may be specified a number of ways:
    - i-xxxxxx: specify an instance by instance id
    - Tag:Value: specify an instance by Tag (e.g. Name:myname)
    - latest: the last launched instance

    Note: tab-completion is available, and completes on currently running instances, so
    you can for example do:
      %ec2ssh i-1<TAB>     - tab complete of instances with a instance id starting i-1.
      %ec2ssh Name:<TAB>   - tab complete of instances with a tag 'Name'.
    """
    
    args = parameter_s.split()
    qs = args.pop()
    ssh_args = ' '.join(args)
    username = ''
    m = re_user.match(qs)
    if m:
        username = m.group(1)
        qs = re_user.sub('', qs)
    
    if not qs:
        raise UsageError, '%ec2ssh needs an instance specifying'

    instances = list(args_instances(qs))
    if len(instances) > 1:
        raise UsageError, "Multiple instances found '%s'" % qs
    inst = instances[0]    
    print 'Instance %s' % inst.id

    try:
        if inst.state == 'pending':
            print 'Waiting for %s pending->running... (Ctrl+C to abort)' % inst.id
            while inst.update() == 'pending':
                time.sleep(1)
    
        if not ssh_live(inst.ip_address):
            count = 0
            print 'Waiting for %s SSH port... (Ctrl+C to abort)' % inst.id
            # must succeed 3 times to be sure SSH is alive
            while count < 3:
                if ssh_live(inst.ip_address):
                    count += 1
                else:
                    count = 0
                time.sleep(1)
                
        if inst.state == 'running':
            print 'Connecting to %s... (Ctrl+C to abort)' % inst.public_dns_name
            ip.system('ssh %s %s%s' % (ssh_args, username, inst.public_dns_name))
        else:
            print 'Failed, instance %s is not running (%s)' % (inst.id, inst.state)
    except KeyboardInterrupt:
        pass
        
    return str(inst.id)

def instance_completer_factory(filters={}):
    def _completer(self, event):
        try:
            global ctx
            res = []
            for i in ctx.instances([]):
                res.append(i.id)
                for k, v in i.tags.iteritems():
                    res.append('%s:%s' % (k, v))
        
            res.extend(STATES)
            res.extend(ARCHS)
            
            return [ r for r in res if r.startswith(event.symbol) ]
        except Exception, ex:
            print ex
    return _completer

######################################################
# generic methods for ec2start, ec2stop, ec2kill
######################################################

def _define_ec2cmd(ip, cmd, verb, state):
    if state:
        filters = [AttributeFilter('state', state)]
    else:
        filters = []
    
    def _ec2cmd(self, parameter_s):
        insts = []
        for inst in args_instances(parameter_s, filters):
            getattr(inst, verb)()
            insts.append(inst)
        return ' '.join( str(inst.id) for inst in insts )
    
    # create function with docstring
    fn = (lambda a,b: _ec2cmd(a,b))
    fn.__doc__ = """%(uverb)s selected %(state)s instances.
        
    Usage:\\
      %%%(cmd)s i-xxxxxxx|Tag:Value|latest
      
    The last parameter selects the instance(s) to %(verb)s. The instance may be specified
    a number of ways:
    - i-xxxxxx: specify an instance by instance id
    - Tag:Value: specify an instance by Tag (e.g. Name:myname)
    - latest: the last launched instance

    Note: tab-completion is available, and completes on appropriate instances, so
    you can for example do:
      %%%(cmd)s i-1<TAB>     - tab complete of instances with a instance id starting i-1.
      %%%(cmd)s Name:<TAB>   - tab complete of instances with a tag 'Name'.
      """ % dict(verb=verb, cmd=cmd, uverb=verb.capitalize(), state=state)
    ip.define_magic(cmd, fn)

    ip.set_hook('complete_command',
                instance_completer_factory(filters=filters),
                re_key = '%?'+cmd)

def ec2din(self, parameter_s):
    """List and describe your instances.

    Usage:\\
      %ec2din [filter ...]
    """
    instances = args_instances(parameter_s)
    print '%-11s %-8s %-9s %-11s %-13s %-17s %s' % ('instance', 'state', 'type', 'zone', 'ami', 'launch time', 'name')
    print '='*95
    for i in instances:
        d = datetime.datetime.strptime(i.launch_time, '%Y-%m-%dT%H:%M:%S.000Z')
        print '%-11s %-8s %-9s %-11s %-13s %-17s %s' % (i.id, i.state[0:8], i.instance_type, i.placement, i.image_id, d.strftime('%Y-%m-%d %H:%M'), i.tags.get('Name',''))

######################################################
# magic ec2watch
######################################################

def _watch_step(parameter_s, instances, monitor_fields):
    new_instances = list(args_instances(parameter_s))
    
    n_i = new_instances[:]
    id_i = [ i.id for i in n_i ]
    for inst in instances:
        if inst.id in id_i:
            n = id_i.index(inst.id)
                
            # compare properties
            changes = []
            for k in monitor_fields:
                v1 = getattr(inst, k)
                v2 = getattr(n_i[n], k)
                if v1 != v2:
                    if v1:
                        if v2:
                            print ' %s  %s: %s->%s' % (inst.id, k, v1, v2)
                        else:
                            print ' %s -%s: %s' % (inst.id, k, v1)
                    else:
                        print ' %s +%s: %s' % (inst.id, k, v2)

            del id_i[n]
            del n_i[n]
        else:
            # instance has gone
            print '-%s' % inst.id
            
    # new instances
    for i in n_i:
        print '+%s' % i.id

    return new_instances

def ec2watch(self, parameter_s):
    """Watch for changes in any properties on instances.

    Usage:\\
      %ec2watch [instance ...]
    """
    interval = 2
    monitor_fields = ['launch_time', 'instance_type', 'state', 'public_dns_name', 'private_ip_address']

    instances = list(args_instances(parameter_s))
    print 'Watching %d instance(s) (press Ctrl+C to end)' % len(instances)
    try:
        while True:
            time.sleep(interval)
            instances = _watch_step(parameter_s, instances, monitor_fields)
    except KeyboardInterrupt:
        pass

######################################################
# %account
######################################################

def magic_account(ip, parameter_s):
    """Switch the account.
    
    Usage:\\
     %account <accountname>|all
    """
    global ctx

    parameter_s = parameter_s.strip()
    if parameter_s == 'all':
        ctx.select_all()
        return
    
    for a in ctx.accounts:
        if parameter_s == a.name:
            ctx.select_account(parameter_s)
            return
        
    raise UsageError, '%%account should be one of %s' % ', '.join(a.name for a in ctx.accounts)

def account_completers(self, event):
    return [a.name for a in ctx.accounts]

######################################################
# %region
######################################################

REGIONS = [ 'us-east-1', 'us-west-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1', 'sa-east-1', 'ap-northeast-1' ]

def magic_region(ip, parameter_s):
    """Switch the default region.
    
    Usage:\\
      %region <regionname>
    """
    global ctx
    
    regions = set(x for x in parameter_s.split() if x)
    if regions.difference(set(REGIONS)):
        raise UsageError, '%region should be in %s' % ', '.join(regions)
    ctx.select_regions(regions)

def region_completers(self, event):
    return REGIONS

class Filter(object):
    @staticmethod
    def _matcher(value, mode):
        if mode == 'startswith':
            def startswith(x):
                if x is None:
                    return False
                return x.startswith(value)
            return startswith
        elif mode == 're':
            r = re.compile(value)
            def re_search(x):
                if x is None:
                    return False
                return r.search(x)
            return re_search
        elif mode == 'in':
            def in_fn(x):
                if x is None:
                    return False
                return [ g.name for g in x if g.name == value ]
            return in_fn
        else:
            return lambda x: x == value
    
    @property
    def type(self):
        return type(self).__name__

class IterableFilter(Filter):
    def filter(self, li):
        return itertools.ifilter(self.select, li)

class AttributeFilter(IterableFilter):
    def __init__(self, attr, value, mode='exact'):
        self.attr = attr
        self.value = value
        self.m = Filter._matcher(value, mode)
        
    def select(self, i):
        return self.m(getattr(i, self.attr, None))
        
    def __str__(self):
        return self.value
    
    @property
    def type(self):
        return self.attr
        
class TagFilter(IterableFilter):
    def __init__(self, name, value, mode='exact'):
        self.name = name
        self.value = value
        self.m = Filter._matcher(value, mode)
        
    def select(self, i):
        return self.m(i.tags.get(self.name))
        
    def __str__(self):
        return '%s:%s' % (self.name, self.value)
    
class LatestFilter(Filter):
    def filter(self, li):
        li = sorted(li, key=lambda i:i.launch_time, reverse=True)
        # return just first
        yield iter(li).next()

    def __str__(self):
        return 'latest'
    
class UnionFilter(Filter):
    def __init__(self, filters):
        self.filters = filters
        
    def filter(self, li):
        for i in li:
            for f in self.filters:
                if f.select(i):
                    yield i
                    break

    def __str__(self):
        return ','.join(str(f) for f in self.filters)
    
    @property
    def type(self):
        return self.filters[0].type

SIZES = ['m1.small', 'm1.large', 'm1.xlarge', 'c1.medium', 'c1.xlarge', 'm2.xlarge', 'm2.2xlarge', 'm2.4xlarge', 'cc1.4xlarge', 't1.micro']
STATES = ('running', 'stopped')
ARCHS = ('i386', 'x86_64')

ATTRIBUTE_FILTERS = {
    'instance_type': SIZES,
    'architecture': ARCHS,
    'state': STATES,
}

######################################################
# %limit
######################################################

def magic_limit(ip, parameter_s):
    """Filter by an attribute.
    
    Usage:\\
      %limit Name:blah
      %limit /app[0-5]/
      %limit group:public
      %limit i-123456 i-234567
      %limit ami-ab1234
      %limit m1.large m1.xlarge
      %limit x86_64
    """
    global ctx
    
    if parameter_s == '-':
        ctx.pop_filter()
        return
    
    for f in parse_filter_list(parameter_s):
        ctx.add_filter(f)        
        
re_inst_id = re.compile(r'i-\w+')
re_tag = re.compile(r'(\w+):(.+)')
re_ami = re.compile(r'ami-\w+')
re_re = re.compile(r'/(.+)/')

def magic_pop(ip, parameter_s):
    global ctx
    ctx.pop_filter()

def parse_filter(arg):
    if arg == 'latest':
        return LatestFilter()
    
    for k, v in ATTRIBUTE_FILTERS.iteritems():
        if arg in v:
            return AttributeFilter(k, arg)

    m = re_inst_id.match(arg)
    if m:
        if len(arg) == 10:
            return AttributeFilter('id', arg)
        else:
            # partial id
            return AttributeFilter('instance_id', arg, 'startswith')

    m = re_ami.match(arg)
    if m:
        return AttributeFilter('image_id', arg, 'startswith')
    
    m = re_tag.match(arg)
    if m:
        if m.group(1) == 'group':
            return AttributeFilter('groups', m.group(2), 'in')
        else:
            return TagFilter(m.group(1), m.group(2))
        
    # Name: regex match
    m = re_re.match(arg)
    if m:
        return TagFilter('Name', m.group(1), 're')
        
    raise UsageError("Filter '%s' not understood" % arg)

def parse_filter_list(parameter_s):
    parameters = set(x for x in parameter_s.split() if x)
    to_add = []
    for arg in parameters:
        f = parse_filter(arg)
        to_add.append(f)
        
    l = []
    for g, li in itertools.groupby(to_add, lambda x: x.type):
        li = list(li)
        if len(li) == 1:
            l.append(li[0])
        else:
            l.append(UnionFilter(li))
    return l
