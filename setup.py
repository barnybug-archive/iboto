from setuptools import setup

__version__ = '0.20.0'

long_description = file('README').read()

setup(name='iboto',
      version=__version__,
      description='Amazon EC2 shell for managing multiple accounts and regions easily',
      long_description=long_description,
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
