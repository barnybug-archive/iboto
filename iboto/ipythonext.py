from IPython.core.error import UsageError

import datetime
import os, re, time, optparse, ConfigParser
import boto.ec2
import socket

def load_ipython_extension(ipython):
    global ip
    ip = ipython

    ip.define_magic('ec2ssh', ec2ssh)
    ip.define_magic('ec2din', ec2din)
    ip.define_magic('ec2-describe-instances', ec2din)
    ip.define_magic('ec2watch', ec2watch)
    ip.define_magic('region', region)
    ip.define_magic('ec2run', ec2run)
    ip.define_magic('ec2-run-instances', ec2run)

    _define_ec2cmd(ip, 'ec2start', 'start', 'start_instances', 'stopped')
    _define_ec2cmd(ip, 'ec2-start-instances', 'start', 'start_instances', 'stopped')
    _define_ec2cmd(ip, 'ec2stop', 'stop', 'stop_instances', 'running')
    _define_ec2cmd(ip, 'ec2-stop-instances', 'stop', 'stop_instances', 'running')

    _define_ec2cmd(ip, 'ec2kill', 'terminate', 'terminate_instances', 'running')
    _define_ec2cmd(ip, 'ec2-terminate-instances', 'terminate', 'terminate_instances', 'running')
    
    ip.set_hook('complete_command', instance_completer_factory({}), re_key = '%?ec2din')
    ip.set_hook('complete_command', instance_completer_factory({}), re_key = '%?ec2watch')
    ip.set_hook('complete_command', ec2run_completers, re_key = '%?ec2run')
    ip.set_hook('complete_command', ec2run_completers, re_key = '%?ec2-run-instances')
    ip.set_hook('complete_command',
                instance_completer_factory(filters={'instance-state-name': 'running'}),
                re_key = '%?ec2ssh')
    ip.set_hook('complete_command', region_completers, re_key = '%?region')
    
    ip.user_ns['ec2_region_name'] = ec2.region.name
    ip.user_ns['ec2'] = ec2

# TODO better exception handling in completers
# TODO handle spaces in tags (completion)
# TODO autogenerate ec2run docstring

region = os.environ.get('EC2_REGION', 'us-east-1')
ec2 = boto.ec2.connect_to_region(region)

# Find out our user id - query for a security group
sg = ec2.get_all_security_groups()[0]
owner_id = sg.owner_id

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

    run_args = {}
    if opts.instance_type:
        run_args['instance_type'] = opts.instance_type
    if opts.key:
        run_args['key_name'] = opts.key
    if opts.instance_count:
        if '-' in opts.instance_count:
            a,b = opts.instance_count.split('-')
            run_args['min_count'] = int(a)
            run_args['max_count'] = int(b)
        else:
            a = int(opts.instance_count)
            run_args['min_count'] = a
            run_args['max_count'] = a
    if opts.group:
        run_args['security_groups'] = opts.group
    if opts.user_data:
        run_args['user_data'] = opts.user_data
    elif opts.user_data_file:
        run_args['user_data'] = file(opts.user_data_file, 'r')
    if opts.monitor:
        run_args['monitoring_enabled'] = True
    if opts.availability_zone:
        run_args['placement'] = opts.availability_zone
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
    r = ec2.run_instances(**run_args)
    
    inst = firstinstance([r])
    return str(inst.id)

def ec2run_completers(self, event):
    cmd_param = event.line.split()
    if event.line.endswith(' '):
        cmd_param.append('')
    arg = cmd_param.pop()
    
    arg = cmd_param.pop()
    if arg in ('-t', '--instance-type'):
        return ['m1.small', 'm1.large', 'm1.xlarge', 'c1.medium', 'c1.xlarge', 'm2.xlarge', 'm2.2xlarge', 'm2.4xlarge', 'cc1.4xlarge', 't1.micro']
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

re_inst_id = re.compile(r'i-\w+')
re_tag = re.compile(r'(\w+):(.+)')
re_ami = re.compile(r'ami-\w+')
states = ('running', 'stopped')
archs = ('i386', 'x86_64')
def resolve_instances(arg, filters=None):
    inst = None
    if arg == 'latest':
        r = ec2.get_all_instances(filters=filters)
        li = sorted(list_instances(r), key=lambda i:i.launch_time)
        if li:
            return li[-1:]
        else:
            return []

    m = re_inst_id.match(arg)
    if m:
        if len(arg) == 10:
            r = ec2.get_all_instances(instance_ids=[arg])
            return list_instances(r)
        else:
            # partial id
            return [ i for i in iter_instances(ec2.get_all_instances()) if i.id.startswith(arg) ]

    m = re_ami.match(arg)
    if m:
        r = ec2.get_all_instances(filters={'image-id': arg})
        return list_instances(r)
    
    m = re_tag.match(arg)
    if m:
        r = ec2.get_all_instances(filters={'tag:%s' % m.group(1): m.group(2)})
        return list_instances(r)
        
    # "running" or "stopped"
    if arg in states:
        r = ec2.get_all_instances(filters={'instance-state-name': arg})
        return list_instances(r)
        
    if arg in archs:
        r = ec2.get_all_instances(filters={'architecture': arg})
        return list_instances(r)
        
    # assume Name: substring match
    r = ec2.get_all_instances()
    return [ i for i in iter_instances(r) if arg in i.tags.get('Name', '') ]

def resolve_instance(arg, filters=None):
    insts = resolve_instances(arg, filters)
    if insts:
        return insts[0]
    else:
        return None

def args_instances(args, default='error'):
    instances = []
    if args:
        # ensure all instances are found before we start them
        for qs in args:
            insts = resolve_instances(qs)
            if not insts:
                raise UsageError, "Instance not found for '%s'" % qs
                return []
            instances.extend(insts)
    elif default=='all':
        instances = list_instances(ec2.get_all_instances())
    else:
        raise UsageError, 'Command needs an instance specifying'

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

    inst = resolve_instance(qs)
    if not inst:
        raise UsageError, "Instance not found for '%s'" % qs
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

def instance_completer_factory(filters):
    def _completer(self, event):
        try:
            instances = []
            r = list_instances(ec2.get_all_instances(filters=filters))
            instances.extend([i.id for i in r])
            for i in r:
                for k, v in i.tags.iteritems():
                    instances.append('%s:%s' % (k, v))
        
            instances.extend(states)
            instances.extend(archs)
            
            return [ i for i in instances if i.startswith(event.symbol) ]
        except Exception, ex:
            print ex
    return _completer

######################################################
# generic methods for ec2start, ec2stop, ec2kill
######################################################

def _define_ec2cmd(ip, cmd, verb, method, state):
    filters = {'instance-state-name': state}
    
    def _ec2cmd(self, parameter_s):
        args = parameter_s.split()
        instances = args_instances(args)
        
        fn = getattr(ec2, method)
        fn([inst.id for inst in instances])
        return ' '.join( str(inst.id) for inst in instances )
    
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
      %ec2din [instance ...]
    """
    args = parameter_s.split()
    instances = args_instances(args, default='all')
    print '%-11s %-8s %-9s %-11s %-13s %-17s %s' % ('instance', 'state', 'type', 'zone', 'ami', 'launch time', 'name')
    print '='*95
    for i in instances:
        d = datetime.datetime.strptime(i.launch_time, '%Y-%m-%dT%H:%M:%S.000Z')
        print '%-11s %-8s %-9s %-11s %-13s %-17s %s' % (i.id, i.state[0:8], i.instance_type, i.placement, i.image_id, d.strftime('%Y-%m-%d %H:%M'), i.tags.get('Name',''))

######################################################
# magic ec2watch
######################################################

def _watch_step(args, instances, monitor_fields):
    new_instances = args_instances(args, default='all')
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
        print '+%s' % inst.id

    return new_instances

def ec2watch(self, parameter_s):
    """Watch for changes in any properties on instances.

    Usage:\\
      %ec2watch [instance ...]
    """
    interval = 2
    monitor_fields = ['launch_time', 'instance_type', 'state', 'public_dns_name', 'private_ip_address']

    args = parameter_s.split()
    instances = args_instances(args, default='all')
    print 'Watching %d instance(s) (press Ctrl+C to end)' % len(instances)
    try:
        while True:
            time.sleep(interval)
            instances = _watch_step(args, instances, monitor_fields)
    except KeyboardInterrupt:
        pass

######################################################
# magic regions
######################################################

regions = [ r.name for r in boto.ec2.regions() ]

def region(self, parameter_s):
    """Switch the default region.
    
    Usage:\\
      %region <regionname>
    """
    parameter_s = parameter_s.strip()
    if parameter_s not in regions:
        raise UsageError, '%region should be one of %s' % ', '.join(regions)
    region = parameter_s
    global ec2, ami, ip
    ec2 = boto.ec2.connect_to_region(region)
    ip.user_ns['ec2'] = ec2
    ip.user_ns['ec2_region_name'] = ec2.region.name

    # update ami list
    ami = build_ami_list()

def region_completers(self, event):
    return regions

def set_region(self, region, args):
    print 'set_region: %s' % region
