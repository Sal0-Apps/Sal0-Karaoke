"""Build client artifacts only when their native implementation changes."""
import argparse
import subprocess


def client_changes(paths):
    android = any(path.startswith(('android/app/src/', 'android/gradle/'))
                  or path in {'android/app/build.gradle.kts', 'android/build.gradle.kts',
                              'android/settings.gradle.kts', 'android/gradle.properties',
                              'android/app/proguard-rules.pro'} for path in paths)
    windows = 'app/youtube_desktop_oauth.py' in paths
    return android, windows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', default='')
    parser.add_argument('--head', default='HEAD')
    args = parser.parse_args()
    before = args.before if args.before and set(args.before) != {'0'} else args.head + '^'
    paths = subprocess.check_output(['git', 'diff', '--name-only', before, args.head], text=True).splitlines()
    android, windows = client_changes(paths)
    print('android=' + str(android).lower())
    print('windows=' + str(windows).lower())
