iboto - an interactive Amazon webservices shell
===============================================

Introduction
------------
iboto offers an interactive shell with the basic set of ec2 commands from the Amazon
command line tools, on steroids!

It adds:

- multiple account support

- multiple region support

- powerful filtering

- tab-completion on arguments:

  + amis

  + instance ids

  + tags

  + zones

  + instance types, etc.

  Saving much fiddly copy-pasting of ids around.
 
- much snappier

  Without having to load all of Java up first before running a command you'll see it's
  much snappier controlling instances compared to the Amazon tools (as great as they are!).
  
- extra functionality:

  + ec2ssh - waits for the instance to be running and SSH to be
    available before connecting; all without having to find and copy
    the public dns name, guess when it's booted fully or even open a
    new terminal for SSH.

  + ec2watch - closely monitor what is happening to your instances whilst you're waiting.
  
- all the nice features of ipython

  History recall, python integration, session recording, configurability, etc.

It's probably best illustrated with a demo session::

    ~ % iboto
    iboto ready
    
    Commands available:
    %ec2din  (aka ls)
    %limit   (aka .)
    %pop     (aka ..)
    %ec2ssh
    %ec2run
    %ec2start
    %ec2stop
    %ec2kill
    %ec2watch
    %account
    %region
    
    '%command?' for more information.
    
    demo1:us-east-1,demo2:eu-west-1
    [1]: limit Role:demo
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [2]: ec2run -T Role:demo
    account (demo1,demo2): demo1
    region: us-east-1
    instance type (m1.small,m1.large,m1.xlarge,c1.medium,c1.xlarge,m2.xlarge,m2.2xlarge,m2.4xlarge,cc1.4xlarge,t1.micro): t1.micro
    number [1]: 
    key: default
    security group (default) [default]: 
    zone (us-east-1a,us-east-1b,us-east-1c,us-east-1d,us-east-1e) [default]: 
    arch (i386,x86_64) [x86_64]: 
    ebs: yes
    ami (lucid,maverick,natty,oneiric,precise,ami-xxxxxx): lucid
    tags: Role:demo
    Out[2]: <Result: success, Instances: i-63f38e07>
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo i-63f38e07
    [3]: ec2ssh
    Instance i-63f38e07
    Waiting for i-63f38e07 pending->running... (Ctrl+C to abort)
    Waiting for i-63f38e07 SSH port... (Ctrl+C to abort)
    Connecting to ec2-107-21-194-97.compute-1.amazonaws.com... (Ctrl+C to abort)
    The authenticity of host 'ec2-107-21-194-97.compute-1.amazonaws.com (107.21.194.97)' can't be established.
    RSA key fingerprint is e7:fe:c9:a9:bb:cc:ca:88:f1:26:0d:86:b0:b7:9d:87.
    Are you sure you want to continue connecting (yes/no)? yes
    Warning: Permanently added 'ec2-107-21-194-97.compute-1.amazonaws.com,107.21.194.97' (RSA) to the list of known hosts.
    Linux domU-12-31-38-01-A9-1C 2.6.32-342-ec2 #43-Ubuntu SMP Wed Jan 4 18:22:42 UTC 2012 x86_64 GNU/Linux
    Ubuntu 10.04.4 LTS
    
    Welcome to Ubuntu!
    ...
    ubuntu@domU-12-31-38-01-A9-1C:~$ logout
    Connection to ec2-107-21-194-97.compute-1.amazonaws.com closed.
    Out[3]: 'i-63f38e07'
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo i-63f38e07
    [4]: ..
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [5]: ec2run -T Role:demo
    account (demo1,demo2): demo2
    region: eu-west-1
    instance type (m1.small,m1.large,m1.xlarge,c1.medium,c1.xlarge,m2.xlarge,m2.2xlarge,m2.4xlarge,cc1.4xlarge,t1.micro): t1.micro
    number [1]: 
    key: default
    security group (default) [default]: 
    zone (eu-west-1a,eu-west-1b,eu-west-1c) [default]: 
    arch (i386,x86_64) [x86_64]: 
    ebs: yes
    ami (lucid,maverick,natty,oneiric,precise,ami-xxxxxx): lucid
    tags: Role:demo
    Out[5]: <Result: success, Instances: i-3affcd73>
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo i-3affcd73
    [6]: ..
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [7]: ls
    account instance    state    type      zone        ami           launch time       name
    =======================================================================================
    demo1 i-63f38e07  running  t1.micro  us-east-1d  ami-349b495d  2012-03-18 17:35  
    demo2 i-3affcd73  pending  t1.micro  eu-west-1b  ami-fb665f8f  2012-03-18 17:36  
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [8]: ec2watch
    Watching 2 instance(s) (press Ctrl+C to end)
     i-3affcd73  state: pending->running
    ^C
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [9]: I.public_dns_name
    Out[9]: 
    [u'ec2-107-21-194-97.compute-1.amazonaws.com',
     u'ec2-176-34-173-80.eu-west-1.compute.amazonaws.com']
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [10]: I.placement
    Out[10]: [u'us-east-1d', u'eu-west-1b']
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [11]: I.add_tag('MyTag', '123')
    This will add_tag 2 instances, ok? (y/N) y
    Out[11]: <Result: success, Instances: i-63f38e07, i-3affcd73>
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [12]: I.tags
    Out[12]: 
    [{u'MyTag': u'123', u'Role': u'demo'},
     {u'MyTag': u'123', u'Role': u'demo'}]
    
    demo1:us-east-1,demo2:eu-west-1 Role:demo
    [13]: limit MyTag:123
    
    demo1:us-east-1,demo2:eu-west-1 MyTag:123
    [14]: I.add_volume(1, '/dev/sdf')
    Creating and attaching volumes...
    Created 2 volumes
    
    demo1:us-east-1,demo2:eu-west-1 MyTag:123
    [15]: ec2ssh latest
    Instance i-3affcd73
    Connecting to ec2-176-34-173-80.eu-west-1.compute.amazonaws.com... (Ctrl+C to abort)
    The authenticity of host 'ec2-176-34-173-80.eu-west-1.compute.amazonaws.com (176.34.173.80)' can't be established.
    RSA key fingerprint is c9:cc:8b:fe:bc:8b:59:6c:3b:0a:07:54:fc:c2:a8:8c.
    Are you sure you want to continue connecting (yes/no)? yes
    Warning: Permanently added 'ec2-176-34-173-80.eu-west-1.compute.amazonaws.com,176.34.173.80' (RSA) to the list of known hosts.
    Linux ip-10-227-133-146 2.6.32-342-ec2 #43-Ubuntu SMP Wed Jan 4 18:22:42 UTC 2012 x86_64 GNU/Linux
    Ubuntu 10.04.4 LTS
    ...
    ubuntu@ip-10-227-133-146:~$ ls -al /dev/sdf
    brw-rw---- 1 root disk 8, 80 2012-03-18 17:38 /dev/sdf
    ubuntu@ip-10-227-133-146:~$ logout
    Connection to ec2-176-34-173-80.eu-west-1.compute.amazonaws.com closed.
    Out[15]: 'i-3affcd73'
    
    demo1:us-east-1,demo2:eu-west-1 MyTag:123
    [16]: ec2kill
    This will terminate 2 instances, ok? (y/N) y
    Out[16]: <Result: success, Instances: i-63f38e07, i-3affcd73>
    
    demo1:us-east-1,demo2:eu-west-1 MyTag:123
    [17]: ls
    account instance    state    type      zone        ami           launch time       name
    =======================================================================================
    demo1 i-63f38e07  shutting t1.micro  us-east-1d  ami-349b495d  2012-03-18 17:35  
    demo2 i-3affcd73  shutting t1.micro  eu-west-1b  ami-fb665f8f  2012-03-18 17:36  
    
    demo1:us-east-1,demo2:eu-west-1 MyTag:123

Installation
------------
Install with your favourite package manager::

    $ pip install iboto

You can then run iboto from your path::

    $ iboto

The default is to start the shell with every account/region visible.
You can limit to a specific account/region from the command line::

    $ iboto demo1 eu-west-1
 
 
Configuration
-------------

The first time iboto is run you'll be taken through a wizard which will configure the
credentials for your account(s).

Help
----
The best documentation is the command documentation accessed by entering '%command?' at the
shell prompt, e.g.::

    '%ec2start?'

    '%limit?'

Future plans
------------
- Add the full set of ec2 tools
- Add further AWS apis.
- Parallel ec2ssh execution for more than one host.
