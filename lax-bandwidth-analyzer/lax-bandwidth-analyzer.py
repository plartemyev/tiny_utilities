#!/usr/bin/env python3

import csv
import bytes_converter
import sys
import numpy

input_file = sys.argv[1]
bulky_list = []

with open(input_file) as input_csv:
    dialect = csv.Sniffer().sniff(input_csv.read(130))
    input_csv.seek(0)
    stat_reader = csv.DictReader(input_csv, restval='', dialect=dialect)
    for row in stat_reader:
        bulky_list.append(bytes_converter.human2bytes(row['Total speed PEAK']))

max_value = max(bulky_list)
print('PEAK speed is: {}bit/s ({} bit/s)'
      .format(bytes_converter.bytes2human(max_value * 8, symbols='iec_ext'), max_value * 8))

percentile_99 = numpy.percentile(bulky_list, 99)
print('99 Percentile is within: {}bit/s ({} bit/s)'
      .format(bytes_converter.bytes2human(percentile_99 * 8, symbols='iec_ext'), percentile_99 * 8))
