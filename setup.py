#!/usr/bin/env python

"""
https://packaging.python.org/guides/distributing-packages-using-setuptools/
https://github.com/pypa/sampleproject
"""

# Always prefer setuptools over distutils
from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

print(f"here = {here}")

# Get the long description from the README file
#long_description = (here / 'README.md').read_text(encoding='utf-8')

# Arguments marked as "Required" below must be included for upload to PyPI.
# Fields marked as "Optional" may be commented out.




if __name__ == "__main__":
    setup(
    #    include_package_data=True,
    #    # If there are data files included in your packages that need to be
    #    # installed, specify them here.
    #    package_data={  # Optional
    #        'data': ['data_file.csv'],
    #    },

    # Although 'package_data' is the preferred approach, in some case you may
    # need to place data files outside of your packages. See:
    # http://docs.python.org/distutils/setupscript.html#installing-additional-files
    #
    # In this case, 'data_file' will be installed into '<sys.prefix>/my_data'
    #data_files=[('my_data', ['data/data_file'])],  # Optional

)
