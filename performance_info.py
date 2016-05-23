#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import glob
import math
import os
import re
import subprocess
import statistics
import logging

logging.basicConfig(level=logging.WARNING, format='[%(levelname)s:%(name)s:%(funcName)s] %(message)s')


class LogStorage:
    def __init__(self, name_prefix):
        self._logger = logging.getLogger(self.__class__.__name__)

        self._name_prefix = name_prefix
        self._out = None

        for file in glob.glob('{}*'.format(name_prefix)):
            os.remove(file)

    def open_index(self, index):
        file_name = '{}{:03}.log'.format(self._name_prefix, index)

        self._logger.info('open file: "{}"'.format(file_name))

        self.close()
        self._out = open(file_name, 'w')

    def append(self, line):
        self._out.write(line)

    def close(self):
        self._logger.info('start')

        if self._out:
            self._logger.info('file "{}" will be close'.format(os.path.basename(self._out.name)))
            self._out.close()
            self._out = None


class DataProvider:
    def __init__(self, name_prefix):
        self._logger = logging.getLogger(self.__class__.__name__)

        self._name_prefix = name_prefix
        self._data = {}

    def data(self):
        return self._data

    def collect(self):
        self._logger.info('start')

        pattern = re.compile('\[Performance\] (.*) ([0-9\.]+) ms')
        data = {}
        self._data = {}

        for file_name in glob.glob('{}*'.format(self._name_prefix)):
            self._logger.debug('in process "{}"'.format(file_name))
            with open(file_name, 'r') as file:
                for line in file:
                    match = pattern.search(line)
                    if match:
                        key = match.group(1)
                        value = float(match.group(2))

                        self._logger.debug('match key = {}; value = {}'.format(key, value))

                        if key in data:
                            data[key].append(value)
                        else:
                            data[key] = [value]
            self._data = data


class LogCollector:
    def __init__(self, adb, package_name, activity_name):
        self._logger = logging.getLogger(self.__class__.__name__)

        self._adb = adb
        self._package_name = package_name
        self._activity_name = activity_name

        self._adb_call = None

        self._progress_callback = None

    def set_progress_callback(self, progress_callback):
        self._logger.info('start')
        self._progress_callback = progress_callback

    def start_task(self):
        self._logger.info('start')
        self._clean_logcat()
        subprocess.check_call([self._adb, 'shell', 'am', 'start', '-n', self._package_name + '/' + self._activity_name],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def stop_task(self):
        self._logger.info('start')

        for i in range(5):
            try:
                if not subprocess.check_call([self._adb, 'shell', 'am', 'force-stop', self._package_name],
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL):
                    break
            except Exception as exception:
                self._logger.error(exception)

    def restart_task(self):
        self._logger.info('start')
        self.stop_task()
        self.start_task()

    def _clean_logcat(self):
        subprocess.check_call([self._adb, 'logcat', '-c'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def _start_logcat(self):
        self._stop_logcat()
        self._adb_call = subprocess.Popen([self._adb, 'logcat'],
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)

    def _stop_logcat(self):
        if self._adb_call:
            self._adb_call.terminate()
            self._adb_call = None

    def collect(self, count, stop_pattern, log_storage):
        self._logger.info('prepare')
        self._collect(5, stop_pattern, None)

        self._logger.info('start collect')
        self._collect(count, stop_pattern, log_storage)

    def _collect(self, count, stop_pattern, log_storage):
        pattern = re.compile(stop_pattern)

        self._start_logcat()

        for i in range(count):
            if self._progress_callback and log_storage:
                self._progress_callback(i)

            self.restart_task()

            if log_storage:
                log_storage.open_index(i)

            while True:
                out_line = None
                try:
                    out_line = str(self._adb_call.stdout.readline().decode())
                except Exception as exception:
                    self._logger.error('Exception: {} with line "{}"'.format(exception, out_line))

                if not out_line and self._adb_call.poll() is not None:
                    break

                if log_storage:
                    log_storage.append(out_line)

                if out_line:
                    match = pattern.search(out_line)
                    if match is not None:
                        break

            if log_storage:
                log_storage.close()

        self._stop_logcat()
        self.stop_task()


class DataAnalyzer:
    def __init__(self):
        self._logger = logging.getLogger(self.__class__.__name__)

        self._data = {}
        self._report = ""

    @staticmethod
    def _percentile(data, percentile):
        size = len(data)
        return sorted(data)[int(math.ceil(size * percentile)) - 1]

    def get_report(self):
        return self._report

    def analyze(self, data_provider):
        self._logger.info('start')

        report = '{pattern:<50}, {mean:>9}, {stdev:>9}, {relative_1:>10}, {min:>9}, {max:>9}, ' \
                 '{percentile_70:>12}, {percentile_80:>12}, {percentile_90:>12}, {percentile_95:>12}\n' \
            .format(pattern='Pattern',
                    mean='mean',
                    stdev='stdev',
                    relative_1='stdev/mean',
                    min='min',
                    max='max',
                    percentile_70='perc_70',
                    percentile_80='perc_80',
                    percentile_90='perc_90',
                    percentile_95='perc_95')

        data = data_provider.data()

        for key in sorted(data.keys()):
            values = data[key]
            mean = statistics.mean(values)
            stdev = statistics.stdev(values) if len(values) > 1 else 0
            relative_1 = stdev / mean if mean else -1
            min_value = min(values)
            max_value = max(values)
            percentile_70 = self._percentile(values, 0.70)
            percentile_80 = self._percentile(values, 0.80)
            percentile_90 = self._percentile(values, 0.90)
            percentile_95 = self._percentile(values, 0.95)

            report += '{key:<50}, {mean:>9.03f}, {stdev:>9.03f}, {relative_1:>10.03f}, {min:>9.03f}, {max:>9.03f}, ' \
                      '{percentile_70:>12.03f}, {percentile_80:>12.03f}, ' \
                      '{percentile_90:>12.03f}, {percentile_95:>12.03f}\n' \
                .format(key=key,
                        mean=mean,
                        stdev=stdev,
                        relative_1=relative_1,
                        min=min_value,
                        max=max_value,
                        percentile_70=percentile_70,
                        percentile_80=percentile_80,
                        percentile_90=percentile_90,
                        percentile_95=percentile_95)

        self._report = report


def main():
    import argparse

    logger = logging.getLogger('main')
    logger.setLevel(logging.INFO)

    def run_count_type(x):
        x = int(x)
        if x < 2:
            raise argparse.ArgumentTypeError('Минимальное значение 2')
        return x

    parser = argparse.ArgumentParser(description='Сбор статистики старта приложения')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Многословный режим')

    parser.add_argument('-f', '--file-prefix',
                        default='log_',
                        help='Префикс файла сбора данных')

    subparser = parser.add_subparsers(dest='command_name',
                                      help='Команда')

    collect_name = 'collect'
    collect_parser = subparser.add_parser(collect_name,
                                          help='Сбор данных с девайса')

    collect_parser.add_argument('-c', '--cmd-adb',
                                default='adb',
                                help='Путь к adb')
    collect_parser.add_argument('-p', '--package',
                                default='ru.dublgis.dgismobile',
                                help='Имя исследуемого пакета')
    collect_parser.add_argument('-a', '--activity',
                                default='.GrymMobileActivity',
                                help='Имя запускаемой активити')
    collect_parser.add_argument('-r', '--run-count',
                                default=30,
                                help='Число запусков',
                                type=run_count_type)
    collect_parser.add_argument('-s', '--search',
                                default='MakeVisible_AddRegion',
                                help='Паттерн по коотрому сбор данных останавливается')

    analyse_name = 'analyse'
    analyse_parser = subparser.add_parser(analyse_name,
                                          help='Анализ собранных данных')

    analyse_parser.add_argument('-r', '--report',
                                default='report.txt',
                                help='Имя файла для сохранения результата')

    args = parser.parse_args()

    if args.verbose:
        logger.info(args)

    auto_mode = args.command_name is None
    args_common = args

    if auto_mode:
        args = parser.parse_args([collect_name], args_common)

    if args.command_name == collect_name:
        log_collector = LogCollector(args.cmd_adb, args.package, args.activity)
        if args.verbose:
            log_collector.set_progress_callback(lambda x: logger.info('{0} of {1}'.format(x + 1, args.run_count)))
        log_collector.collect(args.run_count, args.search, LogStorage(args.file_prefix))

    if auto_mode:
        args = parser.parse_args([analyse_name], args_common)

    if args.command_name == analyse_name:
        data_provider = DataProvider(args.file_prefix)
        data_provider.collect()

        data_analyzer = DataAnalyzer()
        data_analyzer.analyze(data_provider)

        logger.info('Report:\n{0}'.format(data_analyzer.get_report()))

        if args.report is not None:
            with open(args.report, 'w') as out_file:
                print(data_analyzer.get_report(), file=out_file)


if __name__ == "__main__":
    main()
