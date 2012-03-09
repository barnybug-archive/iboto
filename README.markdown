iboto - an interactive Amazon webservices shell
===============================================

Introduction
------------
iboto offers an interactive shell with the basic set of ec2 commands from the Amazon
command line tools, on steroids!

It adds:

- full tab-completion on arguments:
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

It's probably best illustrated with a demo session...

Demo
----
<pre><code>
$ iboto
iboto ready

Commands available:
%ec2ssh
%ec2run   (aka %ec2-run-instances)
%ec2start (aka %ec2-start-instances)
%ec2stop  (aka %ec2-stop-instances)
%ec2kill  (aka %ec2-terminate-instances)
%ec2din   (aka %ec2-describe-instances)
%ec2watch
%region

'%command?' for more information.

eu-west-1 <1>:ec2run -t t[TAB]
eu-west-1 <1>:ec2run -t t1.micro
eu-west-1 <1>:ec2run -t t1.micro -k m[TAB]
eu-west-1 <1>:ec2run -t t1.micro -k mykey
eu-west-1 <1>:ec2run -t t1.micro -k mykey u[TAB]
eu-west-1 <1>:ec2run -t t1.micro -k mykey ubuntu_lucid_
eu-west-1 <1>:ec2run -t t1.micro -k mykey ubuntu_lucid_32_ebs
       Out<1>:'i-e4310993'

eu-west-1 <2>:ec2ssh $_
Waiting for i-e4310993 pending->running...
Waiting for i-e4310993 SSH port...
Connecting to ec2-46-51-139-156.eu-west-1.compute.amazonaws.com...
The authenticity of host 'ec2-46-51-139-156.eu-west-1.compute.amazonaws.com (46.51.139.156)' can't be established.
RSA key fingerprint is c7:6a:f5:a7:38:16:5e:1f:4c:ca:cc:bf:4c:b6:d7:de.
Are you sure you want to continue connecting (yes/no)? yes
Warning: Permanently added 'ec2-46-51-139-156.eu-west-1.compute.amazonaws.com,46.51.139.156' (RSA) to the list of known hosts.
Linux ip-10-235-54-107 2.6.32-309-ec2 #18-Ubuntu SMP Mon Oct 18 21:00:20 UTC 2010 i686 GNU/Linux
Ubuntu 10.04.1 LTS

Welcome to Ubuntu!
...
ubuntu@ip-10-235-54-107:~$ logout
Connection to ec2-46-51-139-156.eu-west-1.compute.amazonaws.com closed.
       Out<2>:'i-e4310993'

eu-west-1 <3>:ec2din 
instance    state    type      zone        ami           launch time               name
===============================================================================================
i-e4310993  running  t1.micro  eu-west-1a  ami-f4340180  2010-12-08T19:30:09.000Z  
eu-west-1 <4>:ec2kill i-e43
       Out<4>:'i-e4310993'

eu-west-1 <5>:ec2watch i-e43
 i-e4310993  state: shutting-down->terminated
 i-e4310993 -public_dns_name: ec2-46-51-139-156.eu-west-1.compute.amazonaws.com
 i-e4310993 -private_ip_address: 10.235.54.107
^Ceu-west-1 <6>:^D
Leaving iboto

</code></pre>

Installation
------------
    $ pip install iboto

You can then run iboto from your path:

    $ iboto
 
AWS Credentials
---------------

Your credentials can be set through environment variables:

    AWS_ACCESS_KEY_ID - Your AWS Access Key ID
    AWS_SECRET_ACCESS_KEY - Your AWS Secret Access Key

Alternatively they can be configured in the boto configuration file,
in short, create  ~/.boto with the content:

    [Credentials]
    aws_access_key_id = <your access key>
    aws_secret_access_key = <your secret key>

Help
----
The best documentation is the command documentation accessed by entering '%command?' at the
shell prompt, e.g.:

    '%ec2start?'

boto
----
You can access the boto ec2 connection object from the shell as the variable 'ec2'.
If you need to script more advanced steps at any point you have the full boto API
available through this, with the niceties of ipython.

AMI tab-completion
-------------------
Any custom AMIs in your account will be added to tab-completion based on the name of
the snapshot it was generated from.

You can also add lists of public pre-built amis.

There are example ami ids for Ubuntu Lucid us-east-1/eu-west-1 under ami/ubuntu-lucid.cfg.
Any .cfg files added to this directory providing sections for your regions will be added to
the tab-completion dictionary.

Future plans
------------
- Add the full set of ec2 tools
- Add further AWS apis.
- Parallel ec2ssh execution for more than one host.
- The sky is the limit!
