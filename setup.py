#!/usr/bin/env python
from os import path
import re
#import glob

from distutils.core import setup
from sendto_cricut import __author__, __version__

# read the contents of your README file
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

m = re.match(r'(.*)\s+<(.*)>', __author__)


setup(name='inkscape-cutcutgo',
      version=__version__,
      description='Inkscape extension for driving a Cricut Maker 1',
      author=m.groups()[0],
      author_email=m.groups()[1],
      url='https://github.com/virtualabs/inkscape-cutcutgo',
      scripts=['sendto_cricut.py', 'sendto_cricut.inx'],
      #scripts=filter(path.isfile,
      #               ['sendto_silhouette.py',
      #                'sendto_silhouette.inx',
      #                'README.md'] +
      #               glob.glob('silhouette-*') +
      #               glob.glob('misc/*') +
      #               glob.glob('misc/*/*')),

      packages=['cutcutgo'],
      license='GPL-2.0',
      classifiers=[
          'License :: OSI Approved :: GNU General Public License v2 (GPLv2)',
          'Environment :: Console',
          'Development Status :: 5 - Production/Stable',
          'Programming Language :: Python :: 3',
          ],
      long_description=long_description,
      long_description_content_type='text/markdown',
      )
