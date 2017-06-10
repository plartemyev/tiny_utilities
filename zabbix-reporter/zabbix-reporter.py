#!/usr/bin/env python3

import pymysql
import re
import logging
import sys
import socket
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def parse_zabbix_server_conf(z_server_conf_file):
    sql_parameters = {
        'DBHost': '',
        'DBUser': '',
        'DBPassword': '',
        'DBName': '',
        'DBSocket': ''
    }

    with open(z_server_conf_file, 'r') as z_conf_f:
        z_server_conf = z_conf_f.read()

    for sql_parameter in sql_parameters:
        try:
            sql_parameters[sql_parameter] = re.search(r'^{}=(.*)'.format(sql_parameter), z_server_conf,
                                                      re.MULTILINE).group(1)
            logging.debug('{} is: {}'.format(sql_parameter, sql_parameters[sql_parameter]))
        except Exception as e:
            logging.debug(e)  # It's perfectly normal if some of these parameters are absent in Zabbix configuration.
            continue
    return sql_parameters


sql_query_zabbix_2x = '''SELECT host, t.description, FROM_UNIXTIME(e.clock) as time,
IF(t.value=1,"Alarm","OK") as trigger_status,
IF(e.acknowledged=1,"Yes","No") as acknowledged,
IF(e.acknowledged=1,a.message,"") as message
FROM triggers t
INNER JOIN functions f ON ( f.triggerid = t.triggerid )
INNER JOIN items i ON ( i.itemid = f.itemid )
INNER JOIN hosts h ON ( i.hostid = h.hostid )
INNER JOIN events e ON ( e.objectid = t.triggerid )
LEFT JOIN acknowledges a ON ( a.eventid = e.eventid )
WHERE (e.eventid DIV 100000000000000)
IN (0)
AND e.object = 0
AND (t.value=1 OR (t.value =0 AND unix_timestamp(now()) - t.lastchange <60))
AND h.status = 0
AND i.status = 0
AND t.status = 0
AND e.eventid = (SELECT max(eventid)
FROM events e
WHERE (e.eventid DIV 100000000000000)
IN (0)
AND e.object = 0
AND (t.value=1 OR (t.value =0 AND unix_timestamp(now()) - t.lastchange <60))
AND h.status = 0
AND i.status = 0
AND t.status = 0
AND e.objectid = t.triggerid
)
GROUP BY host, f.triggerid
ORDER BY t.lastchange DESC;'''

if __name__ == '__main__':
    logging.basicConfig(level='WARNING')
    parameters = parse_zabbix_server_conf('/etc/zabbix/zabbix_server.conf')

    send_ok_statuses = True  # Send summary report even if there is no active triggers detected.
    my_hostname = socket.getfqdn()
    z_url = 'http://{}/zabbix/'.format(my_hostname)
    mail_to = 'sysadmin@example.lab.internal'
    mail_from = 'zabbix-reports@{}'.format(my_hostname)

    if len(parameters['DBHost']) == 0 and len(parameters['DBSocket']) != 0:
        db_conn = pymysql.connect(unix_socket=parameters['DBSocket'], user=parameters['DBUser'],
                                  passwd=parameters['DBPassword'],
                                  db=parameters['DBName'])
    elif len(parameters['DBHost']) != 0:
        db_conn = pymysql.connect(host=parameters['DBHost'], port=3306, user=parameters['DBUser'],
                                  passwd=parameters['DBPassword'],
                                  db=parameters['DBName'])
    else:
        logging.error('Not all necessary parameters present to make MySQL connection')
        sys.exit(1)

    db_cur = db_conn.cursor()
    db_cur.execute(sql_query_zabbix_2x)

    headers = [description[0] for description in db_cur.description]

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Zabbix / Trigger Status / {}'.format(db_cur.rowcount)
    msg['From'] = mail_from
    msg['To'] = mail_to

    html_body_l = []
    html_body = ''

    plain_text_body = 'Sorry, only HTML version available.'

    if db_cur.rowcount == 0 and send_ok_statuses:
        html_body_l.append('<html><head></head><body>')
        html_body_l.append(
            '<h3>This is an automatically generated summary from {}</h3>'.format(my_hostname))
        html_body_l.append('<p>Nothing to report. Just how we like it!</p>')
        html_body_l.append('<p>Log in to Zabbix at <a href={url}>{url}</a></p>'.format(url=z_url))
        html_body_l.append('<p>Regards,</br>{host} (Zabbix Server)</p>'.format(host=my_hostname.split('.')[0]))
        html_body_l.append('</body></html>')
        html_body = '\n'.join(html_body_l)

    elif db_cur.rowcount == 0 and not send_ok_statuses:
        sys.exit(0)  # Why bother - there is no active alerts detected.

    else:
        html_body_l.append('<html><head></head><body>')
        html_body_l.append('<h3>This is an automatically generated summary from {}</h3>'.format(socket.gethostname()))
        html_body_l.append('<p>The following triggers are currently active:</p>')
        html_body_l.append('<table border=1><tr>')
        for tbl_header in headers:
            html_body_l.append('<th>{}</th>'.format(tbl_header))
        html_body_l.append('</tr>')
        for row in db_cur:
            html_body_l.append('<tr>')
            for column in row:
                html_body_l.append('<td>{}</td>'.format(column))
            html_body_l.append('</tr>')
        html_body_l.append('</table>')
        html_body_l.append('<p>Log in to Zabbix at <a href={url}>{url}</a></p>'.format(url=z_url))
        html_body_l.append('<p>Regards,</br>{host} (Zabbix Server)</p>'.format(host=my_hostname.split('.')[0]))
        html_body_l.append('</body></html>')
        html_body = '\n'.join(html_body_l)

    part1 = MIMEText(plain_text_body, 'plain')
    part2 = MIMEText(html_body, 'html')

    # Attach parts into message container.
    # According to RFC 2046, the last part of a multipart message, in this case
    # the HTML message, is best and preferred.
    msg.attach(part1)
    msg.attach(part2)

    # Send the message via local SMTP server.
    s = smtplib.SMTP('localhost')
    # sendmail function takes 3 arguments: sender's address, recipient's address
    # and message to send - here it is sent as one string.
    s.sendmail(mail_from, mail_to, msg.as_string())
    s.quit()
