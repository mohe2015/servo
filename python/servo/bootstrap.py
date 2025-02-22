# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import absolute_import, print_function

from distutils.spawn import find_executable
from distutils.version import LooseVersion
import json
import os
import distro
import shutil
import subprocess
import six
import six.moves.urllib as urllib
from six.moves import input
from subprocess import PIPE
from zipfile import BadZipfile

import servo.packages as packages
from servo.util import extract, download_file, host_triple


def check_gstreamer_lib():
    return subprocess.call(["pkg-config", "--atleast-version=1.16", "gstreamer-1.0"],
                           stdout=PIPE, stderr=PIPE) == 0


def run_as_root(command, force=False):
    if os.geteuid() != 0:
        command.insert(0, 'sudo')
    if force:
        command.append('-y')
    return subprocess.call(command)


def install_linux_deps(context, pkgs_ubuntu, pkgs_fedora, pkgs_void, force):
    install = False
    pkgs = []
    if context.distro in ['Ubuntu', 'Debian GNU/Linux']:
        command = ['apt-get', 'install']
        pkgs = pkgs_ubuntu
        if subprocess.call(['dpkg', '-s'] + pkgs, stdout=PIPE, stderr=PIPE) != 0:
            install = True
    elif context.distro in ['CentOS', 'CentOS Linux', 'Fedora']:
        installed_pkgs = str(subprocess.check_output(['rpm', '-qa'])).replace('\n', '|')
        pkgs = pkgs_fedora
        for p in pkgs:
            command = ['dnf', 'install']
            if "|{}".format(p) not in installed_pkgs:
                install = True
                break
    elif context.distro == 'void':
        installed_pkgs = str(subprocess.check_output(['xbps-query', '-l']))
        pkgs = pkgs_void
        for p in pkgs:
            command = ['xbps-install', '-A']
            if "ii {}-".format(p) not in installed_pkgs:
                install = force = True
                break

    if not install:
        return False

    print("Installing missing dependencies...")
    if run_as_root(command + pkgs, force) != 0:
        raise Exception("Installation of dependencies failed.")
    return True


def install_salt_dependencies(context, force):
    pkgs_apt = ['build-essential', 'libssl-dev', 'libffi-dev', 'python-dev']
    pkgs_dnf = ['gcc', 'libffi-devel', 'python-devel', 'openssl-devel']
    pkgs_xbps = ['gcc', 'libffi-devel', 'python-devel']
    if not install_linux_deps(context, pkgs_apt, pkgs_dnf, pkgs_xbps, force):
        print("Dependencies are already installed")


def gstreamer(context, force=False):
    cur = os.curdir
    gstdir = os.path.join(cur, "support", "linux", "gstreamer")
    if not os.path.isdir(os.path.join(gstdir, "gst", "lib")):
        subprocess.check_call(["bash", "gstreamer.sh"], cwd=gstdir)
        return True
    return False


def bootstrap_gstreamer(context, force=False):
    if not gstreamer(context, force):
        print("gstreamer is already set up")
    return 0


def linux(context, force=False):
    # Please keep these in sync with the packages in README.md
    pkgs_apt = ['git', 'curl', 'autoconf', 'libx11-dev', 'libfreetype6-dev',
                'libgl1-mesa-dri', 'libglib2.0-dev', 'xorg-dev', 'gperf', 'g++',
                'build-essential', 'cmake', 'libssl-dev',
                'liblzma-dev', 'libxmu6', 'libxmu-dev',
                "libxcb-render0-dev", "libxcb-shape0-dev", "libxcb-xfixes0-dev",
                'libgles2-mesa-dev', 'libegl1-mesa-dev', 'libdbus-1-dev',
                'libharfbuzz-dev', 'ccache', 'clang', 'libunwind-dev',
                'libgstreamer1.0-dev', 'libgstreamer-plugins-base1.0-dev',
                'libgstreamer-plugins-bad1.0-dev', 'autoconf2.13',
                'libunwind-dev', 'llvm-dev']
    pkgs_dnf = ['libtool', 'gcc-c++', 'libXi-devel', 'freetype-devel',
                'libunwind-devel', 'mesa-libGL-devel', 'mesa-libEGL-devel',
                'glib2-devel', 'libX11-devel', 'libXrandr-devel', 'gperf',
                'fontconfig-devel', 'cabextract', 'ttmkfdir', 'expat-devel',
                'rpm-build', 'openssl-devel', 'cmake',
                'libXcursor-devel', 'libXmu-devel',
                'dbus-devel', 'ncurses-devel', 'harfbuzz-devel', 'ccache',
                'clang', 'clang-libs', 'llvm', 'autoconf213', 'python3-devel',
                'gstreamer1-devel', 'gstreamer1-plugins-base-devel',
                'gstreamer1-plugins-bad-free-devel', 'libjpeg-turbo-devel',
                'zlib', 'libjpeg']
    pkgs_xbps = ['libtool', 'gcc', 'libXi-devel', 'freetype-devel',
                 'libunwind-devel', 'MesaLib-devel', 'glib-devel', 'pkg-config',
                 'libX11-devel', 'libXrandr-devel', 'gperf', 'bzip2-devel',
                 'fontconfig-devel', 'cabextract', 'expat-devel', 'cmake',
                 'cmake', 'libXcursor-devel', 'libXmu-devel', 'dbus-devel',
                 'ncurses-devel', 'harfbuzz-devel', 'ccache', 'glu-devel',
                 'clang', 'gstreamer1-devel', 'autoconf213',
                 'gst-plugins-base1-devel', 'gst-plugins-bad1-devel']

    installed_something = install_linux_deps(context, pkgs_apt, pkgs_dnf,
                                             pkgs_xbps, force)

    if not check_gstreamer_lib():
        installed_something |= gstreamer(context, force)

    if not installed_something:
        print("Dependencies were already installed!")

    return 0


def salt(context, force=False):
    # Ensure Salt dependencies are installed
    install_salt_dependencies(context, force)
    # Ensure Salt is installed in the virtualenv
    # It's not installed globally because it's a large, non-required dependency,
    # and the installation fails on Windows
    print("Checking Salt installation...", end='')
    reqs_path = os.path.join(context.topdir, 'python', 'requirements-salt.txt')
    process = subprocess.Popen(
        ["pip", "install", "-q", "-I", "-r", reqs_path],
        stdout=PIPE,
        stderr=PIPE
    )
    process.wait()
    if process.returncode:
        out, err = process.communicate()
        print('failed to install Salt via pip:')
        print('Output: {}\nError: {}'.format(out, err))
        return 1
    print("done")

    salt_root = os.path.join(context.sharedir, 'salt')
    config_dir = os.path.join(salt_root, 'etc', 'salt')
    pillar_dir = os.path.join(config_dir, 'pillars')

    # In order to allow `mach bootstrap` to work from any CWD,
    # the `root_dir` must be an absolute path.
    # We place it under `context.sharedir` because
    # Salt caches data (e.g. gitfs files) in its `var` subdirectory.
    # Hence, dynamically generate the config with an appropriate `root_dir`
    # and serialize it as JSON (which is valid YAML).
    config = {
        'hash_type': 'sha384',
        'master': 'localhost',
        'root_dir': salt_root,
        'state_output': 'changes',
        'state_tabular': True,
    }
    if 'SERVO_SALTFS_ROOT' in os.environ:
        config.update({
            'fileserver_backend': ['roots'],
            'file_roots': {
                'base': [os.path.abspath(os.environ['SERVO_SALTFS_ROOT'])],
            },
        })
    else:
        config.update({
            'fileserver_backend': ['git'],
            'gitfs_env_whitelist': 'base',
            'gitfs_provider': 'gitpython',
            'gitfs_remotes': [
                'https://github.com/servo/saltfs.git',
            ],
        })

    if not os.path.exists(config_dir):
        os.makedirs(config_dir, mode=0o700)
    with open(os.path.join(config_dir, 'minion'), 'w') as config_file:
        config_file.write(json.dumps(config) + '\n')

    # Similarly, the pillar data is created dynamically
    # and temporarily serialized to disk.
    # This dynamism is not yet used, but will be in the future
    # to enable Android bootstrapping by using
    # context.sharedir as a location for Android packages.
    pillar = {
        'top.sls': {
            'base': {
                '*': ['bootstrap'],
            },
        },
        'bootstrap.sls': {
            'fully_managed': False,
        },
    }
    if os.path.exists(pillar_dir):
        shutil.rmtree(pillar_dir)
    os.makedirs(pillar_dir, mode=0o700)
    for filename in pillar:
        with open(os.path.join(pillar_dir, filename), 'w') as pillar_file:
            pillar_file.write(json.dumps(pillar[filename]) + '\n')

    cmd = [
        # sudo escapes from the venv, need to use full path
        find_executable('salt-call'),
        '--local',
        '--config-dir={}'.format(config_dir),
        '--pillar-root={}'.format(pillar_dir),
        'state.apply',
        'servo-build-dependencies',
    ]

    if not force:
        print('Running bootstrap in dry-run mode to show changes')
        # Because `test=True` mode runs each state individually without
        # considering how required/previous states affect the system,
        # it will often report states with requisites as failing due
        # to the requisites not actually being run,
        # even though these are spurious and will succeed during
        # the actual highstate.
        # Hence `--retcode-passthrough` is not helpful in dry-run mode,
        # so only detect failures of the actual salt-call binary itself.
        retcode = run_as_root(cmd + ['test=True'])
        if retcode != 0:
            print('Something went wrong while bootstrapping')
            return retcode

        proceed = input(
            'Proposed changes are above, proceed with bootstrap? [y/N]: '
        )
        if proceed.lower() not in ['y', 'yes']:
            return 0

        print('')

    print('Running Salt bootstrap')
    retcode = run_as_root(cmd + ['--retcode-passthrough'])
    if retcode == 0:
        print('Salt bootstrapping complete')
    else:
        print('Salt bootstrapping encountered errors')
    return retcode


def windows_msvc(context, force=False):
    '''Bootstrapper for MSVC building on Windows.'''

    deps_dir = os.path.join(context.sharedir, "msvc-dependencies")
    deps_url = "https://servo-deps-2.s3.amazonaws.com/msvc-deps/"

    def version(package):
        return packages.WINDOWS_MSVC[package]

    def package_dir(package):
        return os.path.join(deps_dir, package, version(package))

    def check_cmake(version):
        cmake_path = find_executable("cmake")
        if cmake_path:
            cmake = subprocess.Popen([cmake_path, "--version"], stdout=PIPE)
            cmake_version_output = six.ensure_str(cmake.stdout.read()).splitlines()[0]
            cmake_version = cmake_version_output.replace("cmake version ", "")
            if LooseVersion(cmake_version) >= LooseVersion(version):
                return True
        return False

    def prepare_file(zip_path, full_spec):
        if not os.path.isfile(zip_path):
            zip_url = "{}{}.zip".format(deps_url, urllib.parse.quote(full_spec))
            download_file(full_spec, zip_url, zip_path)

        print("Extracting {}...".format(full_spec), end='')
        try:
            extract(zip_path, deps_dir)
        except BadZipfile:
            print("\nError: %s.zip is not a valid zip file, redownload..." % full_spec)
            os.remove(zip_path)
            prepare_file(zip_path, full_spec)
        else:
            print("done")

    to_install = {}
    for package in packages.WINDOWS_MSVC:
        # Don't install CMake if it already exists in PATH
        if package == "cmake" and check_cmake(version("cmake")):
            continue

        if not os.path.isdir(package_dir(package)):
            to_install[package] = version(package)

    if not to_install:
        return 0

    print("Installing missing MSVC dependencies...")
    for package in to_install:
        full_spec = '{}-{}'.format(package, version(package))

        parent_dir = os.path.dirname(package_dir(package))
        if not os.path.isdir(parent_dir):
            os.makedirs(parent_dir)

        zip_path = package_dir(package) + ".zip"
        prepare_file(zip_path, full_spec)

        extracted_path = os.path.join(deps_dir, full_spec)
        os.rename(extracted_path, package_dir(package))

    return 0


LINUX_SPECIFIC_BOOTSTRAPPERS = {
    "salt": salt,
    "gstreamer": bootstrap_gstreamer,
}


def get_linux_distribution():
    distrib, version, _ = distro.linux_distribution()
    distrib = six.ensure_str(distrib)
    version = six.ensure_str(version)

    if distrib in ['LinuxMint', 'Linux Mint', 'KDE neon']:
        if '.' in version:
            major, _ = version.split('.', 1)
        else:
            major = version

        if major == '22':
            base_version = '22.04'
        elif major == '21':
            base_version = '21.04'
        elif major == '20':
            base_version = '20.04'
        elif major == '19':
            base_version = '18.04'
        elif major == '18':
            base_version = '16.04'
        else:
            raise Exception('unsupported version of %s: %s' % (distrib, version))

        distrib, version = 'Ubuntu', base_version
    elif distrib == 'Pop!_OS':
        if '.' in version:
            major, _ = version.split('.', 1)
        else:
            major = version

        if major == '22':
            base_version = '22.04'
        elif major == '21':
            base_version = '21.04'
        elif major == '20':
            base_version = '20.04'
        elif major == '19':
            base_version = '18.04'
        elif major == '18':
            base_version = '16.04'
        else:
            raise Exception('unsupported version of %s: %s' % (distrib, version))

        distrib, version = 'Ubuntu', base_version
    elif distrib.lower() == 'elementary':
        if version == '5.0':
            base_version = '18.04'
        elif version[0:3] == '0.4':
            base_version = '16.04'
        else:
            raise Exception('unsupported version of %s: %s' % (distrib, version))
        distrib, version = 'Ubuntu', base_version
    elif distrib.lower() == 'ubuntu':
        if version > '22.04':
            raise Exception('unsupported version of %s: %s' % (distrib, version))
    # Fixme: we should allow checked/supported versions only
    elif distrib.lower() not in [
        'centos',
        'centos linux',
        'debian gnu/linux',
        'fedora',
        'fedora linux',
        'void',
        'nixos',
        'arch',
        'arch linux',
    ]:
        raise Exception('mach bootstrap does not support %s, please file a bug' % distrib)

    return distrib, version


def bootstrap(context, force=False, specific=None):
    '''Dispatches to the right bootstrapping function for the OS.'''

    bootstrapper = None
    if "windows-msvc" in host_triple():
        bootstrapper = windows_msvc
    elif "linux-gnu" in host_triple():
        distrib, version = get_linux_distribution()

        if distrib.lower() == 'nixos':
            print('NixOS does not need bootstrap, it will automatically enter a nix-shell')
            print('Just run ./mach build')
            print('')
            print('You will need to run a nix-shell if you are trying to run any of the built binaries')
            print('To enter the nix-shell manually use:')
            print('  $ nix-shell etc/shell.nix')
            return

        context.distro = distrib
        context.distro_version = version
        bootstrapper = LINUX_SPECIFIC_BOOTSTRAPPERS.get(specific, linux)

    if bootstrapper is None:
        print('Bootstrap support is not yet available for your OS.')
        return 1

    return bootstrapper(context, force=force)
