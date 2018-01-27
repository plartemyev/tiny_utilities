Zabbix aggregated alert reporter. Works by directly querying data from Zabbix database. Current implementation parses
`/etc/zabbix/zabbix_server.conf` and works only with MariaDB/MySQL.

LICENSE
-------
This is free software, distributed under the GPL v.3.

NOTES
-----
As usual with this kind of software :
This software is provided "AS-IS", without any guarantees. It should not do
any harm to your system, but if it does, the author, github, etc... cannot
be held responsible. Use at your own risk. You have been warned.

REQUIREMENTS
-------------
* pymysql
* logging
* smtplib

USAGE
-----
Intended to be run in cron on the same host as Zabbix-server. Tested with Zabbix-LTS 2.2, other releases might need
some changes. Query is stored in `sql_query_zabbix_2x` variable.

### Sample message: This is an automatically generated summary from zabbix-01.lab.internal

The following triggers are currently active:
<table border="1">
<tbody>
<tr>
<th>host</th>
<th>description</th>
<th>time</th>
<th>trigger_status</th>
<th>acknowledged</th>
<th>message</th>
</tr>
<tr>
<td>lxde-test-opensuse42_1.lab.internal</td>
<td>SSH service is down on lxde-test-opensuse42_1.lab.internal</td>
<td>2017-03-26 09:12:42</td>
<td>Alarm</td>
<td>No</td>
<td></td>
</tr>
<tr>
<td>efi-test-tumbleweed.lab.internal</td>
<td>Free disk space is less than 15% on volume /disk/sda</td>
<td>2017-03-25 22:41:11</td>
<td>Alarm</td>
<td>Yes</td>
<td>That's okay.</td>
</tr>
</tbody>
</table>
Log in to Zabbix at [http://zabbix-01.lab.internal/zabbix/](http://zabbix-01.lab.internal/zabbix/)
Regards,  
zabbix-01 (Zabbix Server)
