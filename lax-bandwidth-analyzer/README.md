Quick and hackish utility created to determine peak bandwidth consumption directed to or
from a specified network. I've actually used it to check how steady were some
upstream feeds in a full month timeframe.

LICENSE
-------
This is free software, distributed under the GPL v.3.

NOTES
-----
As usual with this kind of software :
This software is provided "AS-IS", without any guarantees. It should not do
any harm to your system, but if it does, the author, github, etc... cannot
be held responsible. Use at your own risk. You have been warned.

USAGE
-----
It is intended to run for some prolonged period to collect enough data.
I've run it in `screen` session.
Also, some sudoers config may be recommended to run `iftop` as root without password.
Something like `%wheel   ALL= NOPASSWD: /usr/sbin/iftop`
```Shell
screen -dRRS 172.17.172.6_bandwidth_mon
New screen...
./lax-bandwidth-recorder.py 172.17.172.6/32
```
`{}._out.csv` file will appear.
```
./lax-bandwidth-analyzer.py 172.17.172.6_out.csv
PEAK speed is: 11.4 mebibit/s (11995704 bit/s)
99 Percentile is within: 4.8 mebibit/s (5032590.0 bit/s)
```

REQUIREMENTS
-------------
* numpy
* **iftop** and **unbuffer** must be installed in system.
unbuffer is usually in **expect** package.
* Utility was tested with **python 3.2** through **3.6**
