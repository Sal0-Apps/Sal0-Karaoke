"""Build client artifacts only when their native implementation changes."""
import argparse
import subprocess
import re
from pathlib import Path


def client_changes(paths, *, release_version="", android_build=""):
    android = any(path.startswith(('android/app/src/', 'android/gradle/'))
                  or path in {'android/app/build.gradle.kts', 'android/build.gradle.kts',
                              'android/settings.gradle.kts', 'android/gradle.properties',
                              'android/app/proguard-rules.pro'} for path in paths)
    # An explicitly versioned APK is still pending when a failed publication is
    # followed by a packaging/test-only fix. Preserve the Android release intent.
    default = re.search(r'val appVersionName[^\n]*\.orElse\("([^"\n]+)"\)', android_build)
    if release_version and default and default.group(1) == release_version:
        android = True
    windows = 'app/youtube_desktop_oauth.py' in paths
    return android, windows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', default='')
    parser.add_argument('--head', default='HEAD')
    args = parser.parse_args()
    before = args.before if args.before and set(args.before) != {'0'} else args.head + '^'
    paths = subprocess.check_output(['git', 'diff', '--name-only', before, args.head], text=True).splitlines()
    android, windows = client_changes(paths,
        release_version=Path("VERSION").read_text().strip(),
        android_build=Path("android/app/build.gradle.kts").read_text())
    print('android=' + str(android).lower())
    print('windows=' + str(windows).lower())
