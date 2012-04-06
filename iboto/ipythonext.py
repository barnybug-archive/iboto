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
from IPython.utils.io import ask_yes_no
import ConfigParser
from IPython.config.configurable import Configurable
from IPython.utils.traitlets import Unicode, Instance, List, Any
import urllib2

def load_ipython_extension(ipython):
    global ip
    ip = ipython

    ip.define_magic('ec2ssh', ec2ssh)
    ip.define_magic('ec2din', ec2din)
    ip.define_magic('ls', ec2din)
    ip.define_magic('ec2run', ec2run)
    ip.define_magic('ec2watch', ec2watch)

    ip.define_magic('account', magic_account)
    ip.define_magic('region', magic_region)
    ip.define_magic('limit', magic_limit)
    ip.define_magic('.', magic_limit)
    ip.define_magic('pop', magic_pop)
    ip.define_magic('..', magic_pop)

    _define_ec2cmd(ip, 'ec2start', 'start', 'stopped')
    _define_ec2cmd(ip, 'ec2stop', 'stop', 'running')

    _define_ec2cmd(ip, 'ec2kill', 'terminate', None)
    
    ip.set_hook('complete_command', instance_completer_factory(), re_key = '%?ec2din')
    ip.set_hook('complete_command', instance_completer_factory(), re_key = '%?ec2watch')
    ip.set_hook('complete_command', ec2run_parameters.completer, re_key = '%?ec2run')
    ip.set_hook('complete_command', ec2run_parameters.completer, re_key = '%?ec2-run-instances')
    ip.set_hook('complete_command',
                instance_completer_factory(filters={'instance-state-name': 'running'}),
                re_key = '%?ec2ssh')
    ip.set_hook('complete_command', account_completers, re_key = '%?account')
    ip.set_hook('complete_command', region_completers, re_key = '%?region')
    ip.set_hook('complete_command', instance_completer_factory(), re_key = r'%?(limit|\.)')
    
    global iboto
    iboto = IBoto(config=ip.config)
    iboto.configure()
    iboto.command_line()
    ip.user_ns['iboto'] = iboto
    ip.user_ns['I'] = iboto.instances

######################################################
# Constants
######################################################

ARCHS = ('i386', 'x86_64')
SIZES = ['m1.small', 'm1.medium', 'm1.large', 'm1.xlarge', 'c1.medium', 'c1.xlarge', 'm2.xlarge', 'm2.2xlarge', 'm2.4xlarge', 'cc1.4xlarge', 't1.micro']
SIZE_ARCHS = dict( (s, ARCHS) for s in SIZES )
for i in ('m1.large', 'm1.xlarge', 'c1.xlarge', 'm2.xlarge', 'm2.2xlarge', 'm2.4xlarge', 'cc1.4xlarge'):
    SIZE_ARCHS[i] = ('x86_64',)
STATES = ('running', 'stopped')
EBS_ONLY = ('t1.micro',)

ATTRIBUTE_FILTERS = {
    'instance_type': SIZES,
    'architecture': ARCHS,
    'state': STATES,
}

######################################################
# Models
######################################################

class Account(Configurable):
    name = Unicode(config=True)
    access_key = Unicode(config=True)
    secret_key = Unicode(config=True)
    regions = List(Unicode, config=True)
    
    @classmethod
    def default(cls):
        if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
            return Account(name='default',
                           access_key=os.getenv('AWS_ACCESS_KEY_ID'),
                           secret_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                           regions=[os.getenv('EC2_REGION')])
        return 

class Connection(object):
    def __init__(self, acc, reg):
        self.account = acc
        self.region = reg
        self._ec2 = None
        
    def instances(self):
        for r in self.ec2.get_all_instances():
            for i in r.instances:
                i.account = self.account.name # hack - for display
                yield i
        
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
    
class Wizard(object):
    def __init__(self, filename):
        self.filename = filename
        
    def run(self):
        print "Looks like this is the first time you are running iboto, let's configure an account:"
        more = True
        config = ConfigParser.RawConfigParser()
        while more:
            self.account(config)
            print 'iboto supports multiple accounts.'
            more = ask_yes_no('Would you like to configure another account? (y/n)')
            
        with file(self.filename, 'w') as fout:
            config.write(fout)
        print 'Configuration completed.'
        print 'To add or change accounts in future, edit ~/.iboto/settings.\n'
        prompt('Hit enter to continue to load iboto', allow_blank=True)
        
    def account(self, config):
        name = prompt('Account name: ')
        access_key = prompt('AWS Access Key ID: ')
        secret_key = prompt('AWS Secret Access Key: ')
        regions = prompt('Regions (%s): ' % ','.join(REGIONS))
        config.add_section(name)
        config.set(name, 'aws_access_key_id', access_key)
        config.set(name, 'aws_secret_access_key', secret_key)
        config.set(name, 'regions', regions)

class IBoto(Configurable):
    accounts = List(Any, config=True)
    
    def __init__(self, **kwargs):
        super(IBoto, self).__init__(**kwargs)
        self.filters = Filters()
        self.instances = Instances(self.filters)
        
    def select_all(self):
        self.filters[:] = Filters([ ConnectionList( Connection(acc, reg) for acc in self.accounts for reg in acc.regions ) ])
        print self.filters
        
    def select_account(self, name):
        for acc in self.accounts:
            if acc.name == name:
                self.filters[:] = Filters([ ConnectionList( Connection(acc, reg) for reg in acc.regions ) ])
                return True
        return False
            
    def select_regions(self, names):
        filter = []
        accounts = set(conn.account for conn in self.filters[0] )
        self.add_filter(ConnectionList( Connection(acc, reg) for acc in accounts for reg in names ))
        
    def add_filter(self, f):
        self.filters.add_filter(f)
        
    def pop_filter(self):
        self.filters.pop_filter()
        
    def connections(self):
        return self.filters[0]
        
    def __str__(self):
        return str(self.filters)

    def configure(self):
        iboto_cfg = os.path.join(os.getenv('HOME'), '.iboto/settings')
        if not os.path.exists(iboto_cfg):
            Wizard(iboto_cfg).run()

        cfg = ConfigParser.RawConfigParser()
        cfg.read(iboto_cfg)
        accs = []
        for section in cfg.sections():
            access_key = cfg.get(section, 'aws_access_key_id')
            secret_key = cfg.get(section, 'aws_secret_access_key')
            if cfg.has_option(section, 'regions'):
                regions = cfg.get(section, 'regions').split(',')
            else:
                regions = REGIONS
            acc = Account(name=section, access_key=access_key, secret_key=secret_key, regions=regions)
            self.accounts.append(acc)
            
    def command_line(self):
        args = sys.argv[1:]
        if len(args) > 0:
            if not self.select_account(args[0]):
                raise UsageError, "invalid account specified"
            if len(args) > 1:
                self.select_regions([args[1]])
        else:
            self.select_all()

class Filters(list):
    def add_filter(self, f):
        for i, x in enumerate(self):
            if x.type == f.type:
                self[i] = f
                return
        self.append(f)
        
    def pop_filter(self):
        if len(self) > 1:
            self.pop()
    
    def resolve(self, post_filter=None):
        filters = self + (post_filter or [])
        res = None
        for f in filters:
            if not res:
                res = self[0].instances()
            else:
                res = f.filter(res)
        return res
    
    def limit(self, *args):
        return Filters(self + list(args))
    
    def __str__(self):
        return ' '.join( str(f) for f in self )

def wraps(source):
    def _wrapper(dest):
        dest.__doc__ = source.__doc__
        return dest
    return _wrapper

class MultiActions(object):
    @wraps(boto.ec2.instance.Instance.start)
    def start(self):
        return self.limit(StateFilter.stopped)._on_all('start')
        
    @wraps(boto.ec2.instance.Instance.stop)
    def stop(self, force=False):
        return self.limit(StateFilter.not_stopped)._on_all('stop')
        
    @wraps(boto.ec2.instance.Instance.terminate)
    def terminate(self):
        return self.limit(StateFilter.not_terminated)._on_all('terminate')
        
    @wraps(boto.ec2.instance.Instance.reboot)
    def reboot(self):
        return self.limit(StateFilter.not_stopped)._on_all('reboot')
        
    @wraps(boto.ec2.instance.Instance.add_tag)
    def add_tag(self, key, value):
        return self._on_all('add_tag', key, value)
        
    @wraps(boto.ec2.instance.Instance.remove_tag)
    def remove_tag(self, key, value=''):
        return self._on_all('remove_tag', key, value)
        
    def add_volume(self, size, device):
        """Create and attach a volume to each instance.
        
        """
        print 'Creating and attaching volumes...'
        n = 0
        for i in self:
            vol = i.connection.create_volume(size, i.placement)
            vol.attach(i.id, device)
            n += 1
        print 'Created %d volumes' % n
            
    def delete_volume(self, device, force=False):
        """Detach and delete the volume from each instance."""
        print 'Detaching volumes...'
        volumes = []
        for i in self:
            mapping = i.block_device_mapping
            if device in mapping:
                bd = mapping[device]
                i.connection.detach_volume(bd.volume_id, i.id, device, force)
                volumes.extend(i.connection.get_all_volumes([bd.volume_id]))
        
        while volumes:
            for vol in volumes:
                vol.update()
                if vol.status == 'available':
                    vol.delete()
                    del volumes[volumes.index(vol)]
                    
            time.sleep(1)
        
    @property    
    def name(self):
        """Get the Name tag from instances"""
        return [ t.get('Name') for t in self.tags ]
        
    @name.setter
    def name(self, value):
        """Set the Name tag on instances"""
        return self.add_tag('Name', value)
        
    def _on_all(self, cmd, *args, **kwargs):
        li = list(self)
        if len(li) > 1:
            answer = ask_yes_no('This will %s %d instances, ok? (y/N)' % (cmd, len(li)), default='n')
            if not answer:
                return
        for i in li:
            getattr(i, cmd)(*args, **kwargs)
        return Result(li, 'success')
        
    def __getattr__(self, name):
        # credit to idea for this from:
        # http://www.elastician.com/2009/09/stupid-boto-tricks-1-cross-region.html
        results = []
        is_callable = False
        for i in self:
            val = getattr(i, name)
            if callable(val):
                is_callable = True
            results.append(val)
        
        if is_callable:
            functions = results
            def _map(*args, **kwargs):
                results = []
                for fn in functions:
                    results.append(fn(*args, **kwargs))
                return results
            return _map
        else:
            return results
            
    def ls(self, format='%(account)s %(id)-11s %(state)-8s %(instance_type)-9s %(zone)-11s %(ami)-13s %(launch_time)-17s %(name)s'):
        cols = {'account': 'account',
                'id': 'instance',
                'state': 'state',
                'instance_type': 'type',
                'zone': 'zone',
                'ami': 'ami',
                'launch_time': 'launch time',
                'name': 'name'}
        header = format % cols
        print header
        print '=' * len(header)
        for i in self:
            d = datetime.datetime.strptime(i.launch_time, '%Y-%m-%dT%H:%M:%S.000Z')
            fd = {'account': i.account[0:7],
                  'id': i.id,
                  'state': i.state[0:8],
                  'instance_type': i.instance_type,
                  'zone': i.placement[0:10],
                  'ami': i.image_id,
                  'launch_time': d.strftime('%Y-%m-%d %H:%M'),
                  'name': i.tags.get('Name','')}
            print format % fd
            
            
    def __getitem__(self, i):
        try:
            it = iter(self)
            while i > 0:
                it.next()
                i -= 1
            return it.next()
        except StopIteration:
            raise IndexError, 'list index out of range'

    def __len__(self):
        return len(list(iter(self)))
    
class Instances(MultiActions):
    def __init__(self, filters):
        self._filters = filters
                
    def __str__(self):
        return ', '.join( i.id for i in self._filters.resolve() )
        
    def __repr__(self):
        return 'Instances(limit=%s)' % str(self._filters)
        
    def __iter__(self):
        return self._filters.resolve()

    def limit(self, *args):
        return Instances(self._filters.limit(*args))

class Result(MultiActions):
    def __init__(self, instances, status):
        self._instances = instances
        self._status = status
        
    def __iter__(self):
        return iter(self._instances)
        
    def instances(self):
        return iter(self._instances)
        
    def limit(self, *args):
        f = Filters([self])
        return Instances(f).limit(*args)
        
    def __bool__(self):
        return (self._status == 'success')
        
    def __repr__(self):
        return '<Result: %s, Instances: %s>' % (self._status, ', '.join( i.id for i in self._instances ) or 'None')

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

def firstinstance(reservations):
    for r in reservations:
        for i in r.instances:
            return i
    return None

def allinstances(reservations):
    for r in reservations:
        for i in r.instances:
            yield i

######################################################
# magic ec2run
######################################################

class AMI(object):
    def __init__(self, id, name, store, arch, region, aki, virt):
        self.id = id
        self.name = name
        self.store = store
        self.arch = arch
        self.region = region
        self.aki = aki
        self.virt = virt

class Catalogue(list):
    def filter(self, attr):
        for ami in self:
            if not [ True for k, v in attr.iteritems() if getattr(ami, k, None) != v ]:
                yield ami
            
    @classmethod
    def instance(cls):
        inst = cls()
        cls.instance = lambda: inst
        return inst
            
    def names(self):
        return set([ a.name for a in self ])

class UbuntuAMICatalogue(Catalogue):
    def __init__(self, platform):
        self.fetch(platform)
        
    def fetch(self, platform):
        resp = urllib2.urlopen('http://uec-images.ubuntu.com/query/%s/server/released.current.txt' % platform)
        for line in resp.read().split('\n'):
            if not line:
                continue
            vs = line.split('\t')
            dist, s, r, d, store, arch, region, ami, aki, _, virt = vs[0:11]
            if virt == 'hvm':
                continue
            if arch == 'amd64':
                arch = 'x86_64'
            self.append(AMI(ami, dist, store, arch, region, aki, virt))
        
class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None 

    def __call__(cls,*args,**kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance

class AllAMIs(object):
    __metaclass__ = Singleton
    
    def __init__(self):
        self.catalogues = [UbuntuAMICatalogue('lucid'),
                           UbuntuAMICatalogue('maverick'),
                           UbuntuAMICatalogue('natty'),
                           UbuntuAMICatalogue('oneiric'),
                           UbuntuAMICatalogue('precise'),
                        ]
    
    def filter(self, attr):
        for cat in self.catalogues:
            for ami in cat.filter(attr):
                yield ami
                
    def names(self):
        names = set()
        for cat in self.catalogues:
            names.update(cat.names())
        return sorted(names)
        
def resolve_ami(region, arg, attrs):
    amiid = None
    if arg.startswith('ami-'):
        return arg
    else:
        attrs['name'] = arg
        attrs['region'] = region
        all_amis = AllAMIs()
        amis = list(all_amis.filter(attrs))
        if len(amis) == 1:
            return amis[0].id
        elif len(amis) == 0:
            raise UsageError, 'No AMI found: %r' % arg
        else:
            raise UsageError, 'Ambiguous AMI: %r' % arg

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

import readline
class PromptCompleter(object):
    def __init__(self, completions):
        self.completions = completions
        
    def __call__(self, text, state):
        options = [ x for x in self.completions if x.startswith(text) ]
        if state < len(options):
            return options[state]
        return None

def prompt(p, validate=None, allow_blank=False, default=None, choices=None):
    while True:
        if choices:
            cp = PromptCompleter(choices)
            readline.set_completer(cp)
        
        value = raw_input(p)
        if default is not None and value == '':
            if validate:
                return validate(default)
            else:
                return default
        if not allow_blank and value == '':
            continue
        if validate:
            try:
                return validate(value)
            except ValueError, ex:
                print str(ex)
        else:
            return value

class Parameters(object):
    def all_opts(self):
        ret = []
        for o in self.options:
            ret.extend(o.opts)
        return ret
    
    def parser(self):
        p = CustomOptionParser(prog='%ec2run', usage='%prog [options] AMI\n\nLaunch a number of instances of the specified AMI.')
        for o in self.options:
            p.add_option(o.optparse_option())
            
        return p
    
    def _prompt(self, op, value, ctx, choices):
        if value:
            try:
                return op.validate(value, ctx)
            except ValueError:
                pass
    
        message = op.title
        if choices is not None:
            message = '%s (%s)' % (message, ','.join(str(c) for c in choices))
        if op.default is None:
            pass
        elif op.default is Option.missing:
            message = '%s [%s]' % (message, 'default')
        else:
            message = '%s [%s]' % (message, op.default)
        return prompt(message + ': ', validate=(lambda x: op.validate(x, ctx)), default=op.default, choices=choices)
        
    def parse_args(self, args):
        p = self.parser()
        opts, args = p.parse_args(args)
        run_args = opts.__dict__
        for op in self.options:
            if run_args[op.dest] is None:
                if (op.default is Option.missing or op.default is not None) and not op.prompt:
                    if op.default is Option.missing:
                        del run_args[op.dest]
                    elif op.default is not None:
                        run_args[op.dest] = op.default
                        print '%s: %s' % (op.title, op.default)
                else:
                    c = op.choices(run_args)
                    if c and len(c) == 1:
                        if op.action == 'append':
                            run_args[op.dest] = [c[0]]
                        else:
                            run_args[op.dest] = c[0]
                        print '%s: %s' % (op.title, c[0])
                    else:
                        ret = self._prompt(op, run_args[op.dest], run_args, c)
                        if ret is Option.missing:
                            del run_args[op.dest]
                        else:
                            run_args[op.dest] = ret
            else:
                val = run_args[op.dest]
                if isinstance(val, list):
                    val = ', '.join(val)
                print '%s: %s' % (op.title, val)
                
        return run_args, args
    
    def usage(self):
        return self.parser().format_help()
    
    def completer(self, ip, event):
        cmd_param = event.line.split()
        if event.line.endswith(' '):
            cmd_param.append('')
        cmd_param.pop()
        
        arg = cmd_param.pop()
        for o in self.options:
            if arg in o.opts:
                return o.choices({})

        params = self.all_opts()
        # drop from params any already used
        for c in cmd_param:
            for o in self.options:
                if c in o.opts:
                    for a in o.opts:
                        params.remove(a)
        return params

class Option(object):
    missing = object()
    
    def __init__(self, opts, help=None, title=None, metavar=None, choices=None, dest=None, prompt=False, default=None, action=None):
        self.opts = opts
        self.help = help
        self.metavar = metavar
        self._choices = choices
        self.prompt = prompt
        self.default = default
        self.action = action
        self.op = optparse.Option(*opts, dest=dest, help=self.help, metavar=self.metavar, action=action)
        self.dest = self.op.dest
        self.title = title or self.dest
        
    def optparse_option(self):
        return self.op
    
    def choices(self, ctx):
        c = self._choices
        if callable(c):
            c = c(ctx)
        return c
    
    def validate(self, value, ctx):
        if value == self.default:
            return value
        
        c = self.choices(ctx)
        if c is not None:
            if value not in c:
                raise ValueError, "Please choose from: %s" % (', '.join(c))
        return value
    
class EC2RunContext(object):
    def accounts(self, ctx):
        global iboto
        l = []
        for c in iboto.connections():
            if c.account.name not in l:
                l.append(c.account.name)
        return l
    
    def regions(self, ctx):
        global iboto
        r = []
        for c in iboto.connections():
            if c.account.name == ctx['account']:
                r.append(c.region)
        return r
    
    def _connection(self, ctx):
        global iboto
        for c in iboto.connections():
            if c.account.name == ctx['account'] and c.region == ctx['region']:
                return c
    
    def security_groups(self, ctx):
        return [ g.name for g in self._connection(ctx).ec2.get_all_security_groups() ]
        
    def keypairs(self, ctx):
        return [ k.name for k in self._connection(ctx).ec2.get_all_key_pairs() ]
        
    def zones(self, ctx):
        return [ z.name for z in self._connection(ctx).ec2.get_all_zones() ]
        
    def archs(self, ctx):
        return SIZE_ARCHS[ ctx['instance_type'] ]
    
    def ebss(self, ctx):
        if ctx['instance_type'] in EBS_ONLY:
            return ('yes',)
        else:
            return ('yes','no')
            
    def amis(self, ctx):
        # limit ami list to those with available region/arch/store
        amis = AllAMIs().filter({'region': ctx['region'],
                                 'arch': ctx['arch'],
                                 'store': (ctx['ebs'] and 'ebs' or 'instance')})
        li = list(set( a.name for a in amis ))
        li.sort()
        li.append(AMIMatch())
        return li

class AMIMatch(object):
    def __eq__(self, x):
        return bool(re_ami.match(x))
        
    def __str__(self):
        return 'ami-xxxxxx'
        
class EC2RunParameters(Parameters):
    context = EC2RunContext()
    options = [
        Option(['--account'], title='account', choices=context.accounts, metavar='ACCOUNT', help='Account in which to launch instance.'),
        Option(['--region'], title='region', choices=context.regions, metavar='REGION', help='Region in which to launch instance.'),
        Option(['-t', '--instance-type'], title='instance type', choices=SIZES, metavar='TYPE', help='Specifies the type of instance to be launched.'),
        Option(['-n', '--instance-count'], title='number', default='1', prompt=True, metavar='MIN-MAX', help='The number of instances to attempt to launch.'),
        Option(['-k', '--key'], title='key', dest='key_name', metavar='KEYPAIR', choices=context.keypairs, help='Specifies the key pair to use when launching the instance(s).'),
        Option(['-g', '--group'], title='security group', dest='security_groups', metavar='GROUP', default=Option.missing, prompt=True, choices=context.security_groups, action='append', help='Specifies the security group.'),
        Option(['-d', '--user-data'], metavar='DATA', default=Option.missing, help='Specifies the user data to be made available to the instance(s) in this reservation.'),
        Option(['-f', '--user-data-file'], metavar='DATA-FILE', default=Option.missing, help='Specifies the file containing user data to be made available to the instance(s) in this reservation.'),
        Option(['-m', '--monitor'], action='store_true', default=Option.missing, help='Enables monitoring of the specified instance(s).'),
        Option(['-z', '--availability-zone'], dest='placement', title='zone', metavar='ZONE', prompt=True, choices=context.zones, default=Option.missing, help='Specifies the availability zone to launch the instance(s) in.'),
        Option(['--disable-api-termination'], action='store_true', default=Option.missing, help='Indicates that the instance(s) may not be terminated using the TerminateInstances API call.'),
        Option(['--instance-initiated-shutdown-behavior'], default=Option.missing, metavar='BEHAVIOR', help='Indicates what the instance(s) should do if an on instance shutdown is issued.'),
        Option(['--arch'], default='x86_64', dest='arch', prompt=True, metavar='ARCH', choices=context.archs, help='Which architecture to launch.'),
        Option(['--ebs'], default='yes', dest='ebs', prompt=True, metavar='EBS', choices=context.ebss, help='EBS or not.'),
        Option(['--ami'], dest='ami', prompt=True, metavar='AMI', choices=context.amis, help='AMI to launch'),
        Option(['-T', '--tags'], metavar='TAG', action='append', default=Option.missing, help='Add a tag to the launched instance.'),
    ]
        
class CustomOptionParser(optparse.OptionParser):
    def exit(self, status=0, msg=''):
        raise ValueError, msg
    
ec2run_parameters = EC2RunParameters()

def ec2run(self, parameter_s):
    try:
        run_args, args = ec2run_parameters.parse_args(parameter_s.split())
    except ValueError, ex:
        print str(ex)
        return

    account = run_args.pop('account')
    region = run_args.pop('region')
    global iboto
    for c in iboto.connections():
        if c.account.name == account and c.region == region:
            break
    connection = c
    
    instance_count = run_args.pop('instance_count')
    p = instance_count.split('-')
    if len(p) == 2:
        run_args['min_count'], run_args['max_count'] = p
    else:
        run_args['min_count'] = run_args['max_count'] = p[0]
        
    arch = run_args.pop('arch')
    ebs = run_args.pop('ebs')
    aminame = run_args.pop('ami')
    tags = run_args.pop('tags', None)
        
    run_args['image_id'] = resolve_ami(region, aminame, {'arch': arch, 'store': (ebs == 'yes' and 'ebs' or 'instance')})
    r = connection.ec2.run_instances(**run_args)
    
    if tags:
        for tag in tags:
            if ':' in tag:
                for i in allinstances([r]):
                    key, value = tag.split(':', 1)
                    i.add_tag(key, value)
            else:
                print 'Ignoring tag %s' % tag
    
    inst = firstinstance([r])
    iboto.add_filter(AttributeFilter('id', inst.id))
    return Result([inst], 'success')

ec2run.__doc__ = ec2run_parameters.usage()

def args_instances(parameter_s):
    if parameter_s:
        filters = parse_filter_list(parameter_s)
    else:
        filters = []
    
    instances = iboto.instances.limit(*filters)
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
    if args:
        qs = args.pop()
    else:
        qs = ''
    ssh_args = ' '.join(args)
    username = ''
    m = re_user.match(qs)
    if m:
        username = m.group(1)
        qs = re_user.sub('', qs)
    
    instances = list(args_instances(qs))
    if len(instances) > 1:
        raise UsageError, "%d instances found - ec2ssh only supports a single host" % len(instances)
    inst = instances[0]    
    print 'Instance %s' % inst.id
    
    if inst.state == 'stopped':
        raise UsageError, "Instance is stopped - please 'ec2start', then 'ec2ssh'"

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
            global iboto
            res = []
            for i in iboto.instances:
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
    
    def _ec2cmd(ip, parameter_s):
        instances = args_instances(parameter_s)
        return getattr(instances, verb)()
    
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
    instances.ls()

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
    global iboto

    parameter_s = parameter_s.strip()
    if parameter_s == 'all':
        iboto.select_all()
        return
    
    for a in iboto.accounts:
        if parameter_s == a.name:
            iboto.select_account(parameter_s)
            return
        
    raise UsageError, '%%account should be one of %s' % ', '.join(a.name for a in iboto.accounts)

def account_completers(self, event):
    return [a.name for a in iboto.accounts]

######################################################
# %region
######################################################

REGIONS = [ 'us-east-1', 'us-west-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1', 'sa-east-1', 'ap-northeast-1' ]

def magic_region(ip, parameter_s):
    """Switch the default region.
    
    Usage:\\
      %region <regionname>
    """
    global iboto
    
    regions = set(x for x in parameter_s.split() if x)
    if regions.difference(set(REGIONS)):
        raise UsageError, '%region should be in %s' % ', '.join(regions)
    iboto.select_regions(regions)

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
    
class StateFilter(IterableFilter):
    def __init__(self, states):
        self.states = states
        
    def select(self, i):
        return i.state in self.states
        
    def __str__(self):
        return ','.join(self.states)
        
StateFilter.stopped = StateFilter(['stopped'])
StateFilter.not_stopped = StateFilter(['running', 'pending'])
StateFilter.not_terminated = StateFilter(['running', 'pending', 'stopped', 'stopping'])

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
    global iboto
    
    if parameter_s == '-':
        iboto.pop_filter()
        return
    
    for f in parse_filter_list(parameter_s):
        iboto.add_filter(f)
        
re_inst_id = re.compile(r'i-\w+')
re_tag = re.compile(r'(\w+):(.+)')
re_ami = re.compile(r'ami-\w+')
re_re = re.compile(r'/(.+)/')

def magic_pop(ip, parameter_s):
    global iboto
    iboto.pop_filter()

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
            return AttributeFilter('id', arg, 'startswith')

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
