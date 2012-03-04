from setuptools import setup

__version__ = '0.12.1'

setup(name='iboto',
      version=__version__,
      description='An interactive Amazon webservices shell',
      long_description='iboto offers an interactive shell with the basic set of ec2 commands from the Amazon command line tools, on steroids!',
      license='MIT',
      author='Barnaby Gray',
      author_email='barnaby@pickle.me.uk',
      url='http://github.com/barnybug/iboto/',
      install_requires=['boto >= 2.1', 'ipython >= 0.11'],
      packages=['iboto'],
      scripts=['scripts/iboto'],
      classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Utilities",
        "License :: OSI Approved :: MIT License",
        ],
      )
