#! /usr/bin/env python3
from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='vfio-isolate',
    version='0.3.1',
    description='Commandline tool to facilitate CPU core isolation',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/spheenik/vfio-isolate',
    author='Martin Schrodt (spheenik)',
    author_email='martin@schrodt.org',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: System Administrators',
        'Topic :: System :: Systems Administration',
        'Operating System :: POSIX :: Linux',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    keywords='vfio cpu isolation',
    install_requires=[
        'click~=7.1.2',
        'psutil~=5.7.0',
        'parsimonious~=0.8.1',
    ],
    packages=find_packages(),
    python_requires='>=3.6, <4',
    entry_points={
        'console_scripts': [
            'vfio-isolate=vfio_isolate:run_cli',
        ],
    }
)
