# ipython module

import os, re, optparse, ConfigParser
import IPython.ipapi
from IPython.ipstruct import Struct
import boto.ec2
import config

ip = IPython.ipapi.get()
region = getattr(config, 'DEFAULT_REGION', 'us-east-1')
creds = dict(aws_access_key_id=config.AWS_ACCESS_KEY_ID,
             aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY)
ec2 = boto.ec2.connect_to_region(region, **creds)
ip.user_ns['ec2'] = ec2

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

def iterinstances(reservations):
    for r in reservations:
        for i in r.instances:
            yield i

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
ami = build_ami_list()

def expose_magic(fn):
    ip.expose_magic(fn.__name__, fn)

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

@expose_magic
def ec2run(self, parameter_s):
    """Launch a number of instances of the specified AMI.

    Usage:\\
      %ec2run [options] AMI
      These options from the Amazon command line tool are supporting:
      -k, --key KEYPAIR
      
    """
    try:
        opts,args = ec2run_parser.parse_args(parameter_s.split())
    except Exception, ex:
        raise IPython.ipapi.UsageError, str(ex)
        return

    if not args:
        raise IPython.ipapi.UsageError, '%ec2run needs an AMI specifying'
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
    
    inst = firstinstance(r)
    return str(inst.id)

def ec2run_completers(self, event):
    cmd_param = event.line.split()
    if event.line.endswith(' '):
        cmd_param.append('')
    arg = cmd_param.pop()
    #if arg.startswith('-'):
    #    ret = []
    #    for o in ec2run_parser.option_list:
    #        ret.extend(o._short_opts + o._long_opts)
    #    return ret
    
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

ip.set_hook('complete_command', ec2run_completers, re_key = '%?ec2run')

re_inst_id = re.compile(r'i-\w+')
re_tag = re.compile(r'(\w+):(.+)')
def resolve_instance(arg):
    inst = None
    if arg == 'latest':
        r = ec2.get_all_instances(filters={'instance-state-name':'running'})
        li = sorted(iterinstances(r), key=lambda i:i.launch_time)
        if li:
            inst = li[-1]
    else:
        m = re_inst_id.match(arg)
        if m:
            r = ec2.get_all_instances(instance_ids=[arg])
            inst = firstinstance(r)
        else:
            m = re_tag.match(arg)
            if m:
                r = ec2.get_all_instances(filters={'tag:%s' % m.group(1): m.group(2)})
                inst = firstinstance(r)

    return inst

######################################################
# magic ec2ssh
######################################################

re_user = re.compile('^(\w+@)')

@expose_magic
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
    
    args = parameter_s.split(' ')
    qs = args.pop()
    ssh_args = ' '.join(args)
    username = ''
    m = re_user.match(qs)
    if m:
        username = m.group(1)
        qs = re_user.sub('', qs)
    
    if not qs:
        raise IPython.ipapi.UsageError, '%ec2ssh needs an instance specifying'

    inst = resolve_instance(qs)
    if not inst:
        print 'Instance not found for %s' % qs
        return
        
    if inst.state == 'pending':
        print 'Waiting for %s pending->running...' % inst.id
        while inst.update() == 'pending':
            time.sleep(1)
            
    if inst.state == 'running':
        print 'Connecting to %s...' % inst.public_dns_name
        ip.system('ssh %s %s%s' % (ssh_args, username, inst.public_dns_name))
    else:
        print 'Failed, instance %s is not running (%s)' % (inst.id, inst.state)
        
    return inst

def ec2ssh_completers(self, event):
    instances = []
    running = list(iterinstances(ec2.get_all_instances(filters={'instance-state-name': 'running'})))
    instances.extend([i.id for i in running])
    for i in running:
        for k, v in i.tags.iteritems():
            instances.append('%s:%s' % (k, v))
        
    return instances
ip.set_hook('complete_command', ec2ssh_completers, re_key = '%?ec2ssh')

######################################################
# magic regions
######################################################

regions = [ r.name for r in boto.ec2.regions(**creds) ]

@expose_magic
def region(self, parameter_s):
    """Switch the default region.
    
    Usage:\\
      %region <regionname>
    """
    parameter_s = parameter_s.strip()
    if parameter_s not in regions:
        raise IPython.ipapi.UsageError, '%region should be one of %s' % ', '.join(regions)
    region = parameter_s

    global ec2, ami
    ec2 = boto.ec2.connect_to_region(region, **creds)    
    ip.user_ns['ec2'] = ec2

    # update ami list
    ami = build_ami_list()

def region_completers(self, event):
    return regions
ip.set_hook('complete_command', region_completers, re_key = '%?region')

def set_region(self, region, args):
    print 'set_region: %s' % region

######################################################
# ipython environment
######################################################

# make boto available in shell    
ip.ex('import boto.ec2')

# set variables in ipython ns

# set prompt to region name
o = ip.options
o.prompt_in1 = r'${ec2.region.name} <\#>:'
o.prompt_in2 = r'   .\D.:'
o.prompt_out = r'Out<\#>:'

# remove blank lines between
o.separate_in = ''
o.separate_out = '\n'
o.separate_out2 = ''
