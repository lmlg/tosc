import glob
import os
import shutil
import sys

from setuptools import setup

base_path = os.path.dirname (__file__)

with open (os.path.join (base_path, "VERSION")) as version:
  VERSION = version.read().rstrip ()
with open (os.path.join (base_path, "tosc/_version.py"), "w") as vfile:
  vfile.write ('__version__ = "%s"' % VERSION)
with open (os.path.join (base_path, "requirements.txt")) as reqs:
  requirements = reqs.read ()

setup (
  name = "tosc",
  version = VERSION,
  description = "Distributed data structures for Python",
  author = "Luciano Lo Giudice & Agustina Arzille",
  author_email = "lmlogiudice@gmail.com",
  maintainer = "Luciano Lo Giudice",
  maintainer_email = "lmlogiudice@gmail.com",
  url = "https://github.com/lmlg/tosc/",
  license = "GPLv3",
  packages = ["tosc", "tosc.backends"],
  package_dir = {"tosc": "tosc"},
  tests_require = ["pytest"],
  test_suite = "tests",
  install_requires = requirements,
  zip_safe = False,
)
