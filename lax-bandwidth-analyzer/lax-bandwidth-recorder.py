#!/usr/bin/env python3

import datetime
import subprocess
import sys

target_host = str(sys.argv[1])
t_host_clean = target_host.split("/")[0]
commandline_opts = ["unbuffer", "sudo", "iftop", "-F", target_host, "-NBt"]  # piped commands are usually buffered.
constructed_commandline = " ".join(commandline_opts)

delimiter = ";"
csv_header = "Time;Receiving speed;Sending speed;Receiving speed PEAK;Sending speed PEAK;Total speed PEAK;\
Traffic received;Traffic sent;Traffic total\n"

block_beginning = "# Host name"
block_end = "===="
receive_sign = "=>"
send_sign = "<="
raw_data = []

filename = t_host_clean + "_out.csv"


class DataBlock:
    """Represents one output from iperf.
    Speeds are 2 seconds average in byte/s"""

    def __init__(self, output_lines):
        self.speed_in = 0
        self.speed_out = 0
        self.speed_peak_in = 0
        self.speed_peak_out = 0
        self.speed_peak_total = 0
        self.traffic_in = 0
        self.traffic_out = 0
        self.traffic_total = 0
        # print("initialized block {}".format(self.strings))

        for output_line in output_lines:
            output_line_strings = output_line.split()
            # out/in is reversed intentionally
            if receive_sign in output_line:
                self.speed_in = output_line_strings[3]
            elif send_sign in output_line:
                self.speed_out = output_line_strings[2]
            elif "Peak rate" in output_line:
                self.speed_peak_out = output_line_strings[4]
                self.speed_peak_in = output_line_strings[3]
                self.speed_peak_total = output_line_strings[5]
            elif "Cumulative" in output_line:
                self.traffic_out = output_line_strings[3]
                self.traffic_in = output_line_strings[2]
                self.traffic_total = output_line_strings[4]

    def join_results(self):
        if str(self.speed_in) == str(self.speed_out) == "0B":
            return None

        time = datetime.datetime.today()
        results_line = (str(time), str(self.speed_in), str(self.speed_out), str(self.speed_peak_in),
                        str(self.speed_peak_out), str(self.speed_peak_total), str(self.traffic_in),
                        str(self.traffic_out), str(self.traffic_total))
        csv_line = delimiter.join(results_line)
        return csv_line + '\n'


def run(command: str):
    popen = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
    return iter(popen.stdout.readline, b'')


with open(filename, 'w') as outfile:
    outfile.write(csv_header)
    outfile.flush()
    print(csv_header, end='')

    for line in run(constructed_commandline):
        line = line.decode()  # It is bytes not str.

        if block_beginning in line:
            raw_data = []
        elif block_end in line:
            # We've found block end - process it.
            data_block = DataBlock(raw_data)
            rl = data_block.join_results()
            if rl is not None:
                print(rl, end='')
                outfile.write(rl)
                outfile.flush()

            raw_data = []
        else:
            raw_data.append(line)
