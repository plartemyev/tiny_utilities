#!/usr/bin/python3
import csv
import bytes_converter
import sys
import numpy

input = sys.argv[1]
bulky_list = []

with open(input) as inputcsv:
    dialect = csv.Sniffer().sniff(inputcsv.read(130))
    inputcsv.seek(0)
    statreader = csv.DictReader(inputcsv, restval='', dialect=dialect)
    for row in statreader:
        bulky_list.append(bytes_converter.human2bytes(row['Total speed PEAK']))

max_value = max(bulky_list)
print('PEAK speed in bytes/s:', max_value, '\t\t\thuman readable:', bytes_converter.bytes2human(max_value))

percentile_99 = numpy.percentile(bulky_list, 99)
print('99 Percentile is within bytes/s:', percentile_99, '\thuman readable:',
      bytes_converter.bytes2human(percentile_99))
