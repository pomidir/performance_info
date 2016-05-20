#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import subprocess
import statistics


class StatCollector:
    def __init__(self, adb, package_name, activity_name):
        self._adb = adb
        self._package_name = package_name
        self._activity_name = activity_name

        self._adb_call = None
        self._data = {}

        self._progress_callback = None

    def set_progress_callback(self, progress_callback):
        self._progress_callback = progress_callback

    def data(self):
        return self._data

    def _get_data(self, pattern):
        return self._data[pattern]

    def min(self, pattern):
        return min(self._data[pattern])

    def max(self, pattern):
        return max(self._data[pattern])

    def mean(self, pattern):
        return statistics.mean(self._data[pattern])

    def stdev(self, pattern):
        data = self._get_data(pattern)

        if len(data) == 1:
            return 0

        return statistics.stdev(data)

    def start_task(self):
        subprocess.check_call([self._adb, 'shell', 'am', 'start', '-n', self._package_name + '/' + self._activity_name],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def stop_task(self):
        subprocess.check_call([self._adb, 'shell', 'am', 'force-stop', self._package_name],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def restart_task(self):
        self.stop_task()
        self.start_task()

    def _start_logcat(self):
        subprocess.check_call([self._adb, 'logcat', '-c'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

        self._stop_logcat()
        self._adb_call = subprocess.Popen([self._adb, 'logcat'],
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)

    def _stop_logcat(self):
        if self._adb_call is not None:
            self._adb_call.terminate()
            self._adb_call = None

    def get_time(self, search_patterns):
        patterns = {search_pattern: re.compile(search_pattern) for search_pattern in search_patterns}
        time_result = {}

        while True:
            out_line = str(self._adb_call.stdout.readline())

            if out_line == '' and self._adb_call.poll() is not None:
                break

            if out_line:
                for search_pattern, pattern in patterns.items():
                    match = pattern.search(out_line)
                    if match is not None:
                        time_result[search_pattern] = float(match.group(1))
                        patterns.pop(search_pattern, None)

                        if not patterns:
                            return time_result

                        break

        return None

    def collect(self, count, search_patterns):
        self._start_logcat()

        self._data = {key: [] for key in search_patterns}

        for i in range(count):
            self.restart_task()
            time_value = self.get_time(search_patterns)
            if time_value is None:
                raise Exception('On iteration {0} value not found'.format(i))
            for search_pattern, time in time_value.items():
                self._data[search_pattern].append(time)

            if self._progress_callback is not None:
                self._progress_callback(i)

        self._stop_logcat()
        self.stop_task()

    def get_report(self):
        report = ''

        for pattern in sorted(self._data.keys()):
            mean = self.mean(pattern)
            stdev = self.stdev(pattern)
            relative_1 = stdev / mean if mean else -1
            min = self.min(pattern)
            max = self.max(pattern)
            delta = max - min
            relative_2 = delta / mean if mean else -1

            report += '"{pattern}": {mean:.03f} +/- {stdev:.03f}/{relative_1:.03f}' \
                      ' [{min:.03f}, {max:.03f}]({delta:.03f}/{relative_2:.03f})\n' \
                .format(pattern=pattern,
                        mean=mean,
                        stdev=stdev,
                        relative_1=relative_1,
                        min=min,
                        max=max,
                        delta=delta,
                        relative_2=relative_2)

        return report


def main():
    import argparse

    def run_count_type(x):
        x = int(x)
        if x < 2:
            raise argparse.ArgumentTypeError('Minimum is 2')
        return x

    parser = argparse.ArgumentParser(description='Application start statistics collection.')

    parser.add_argument('-c', '--cmd-adb',
                        default='adb',
                        help='adb path')
    parser.add_argument('-p', '--package',
                        default='ru.dublgis.dgismobile',
                        help='Package name')
    parser.add_argument('-a', '--activity',
                        default='.GrymMobileActivity',
                        help='Activity name')
    parser.add_argument('-r', '--run-count',
                        default=15,
                        help='Count of run',
                        type=run_count_type)
    parser.add_argument('-s', '--search',
                        default=['SinceOnCreate::BeforeSplashShown ([0-9]+) ms',
                                 'SplashLifetime: ([0-9]+) ms',
                                 'ApplicationTime::SplashHide ([0-9]+) ms'],
                        nargs='+',
                        help='Search pattern')
    parser.add_argument('-d', '--data',
                        default=None,
                        help='Data file name')
    parser.add_argument('-o', '--out',
                        default=None,
                        help='Report file name')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Verbose')

    args = parser.parse_args()

    stat_collector = StatCollector(args.cmd_adb, args.package, args.activity)
    if args.verbose:
        stat_collector.set_progress_callback(lambda x: print('{0} of {1}:\n{2}'.format(x + 1,
                                                                                        args.run_count,
                                                                                        stat_collector.get_report())))

    stat_collector.collect(args.run_count, args.search)

    if args.data is not None:
        with open(args.data, 'w') as data_file:
            print(stat_collector.data(), file=data_file)

    print('Report:\n{0}'.format(stat_collector.get_report()))

    if args.out is not None:
        with open(args.out, 'w') as out_file:
            print(stat_collector.get_report(), file=out_file)


if __name__ == "__main__":
    main()
