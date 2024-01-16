from prometheus_client import start_http_server, Counter
import time
import pymysql
import argparse

# Start a Prometheus counter metric
dmarc_srg_reports_total = Counter(
    'dmarc_srg_reports_total',
    'Number of messages reported to dmarc-srg',
    ['domain_fqdn', 'report_org', 'record_dkim_align', 'record_spf_align']
)

# Dictionary to store summed up total_rcount values
new_state = {}
old_state = {}

# id of latest loaded report
last_report_id = 0

# Function to fetch data from MySQL and update Prometheus counter
def fetch_and_update_metrics(db_host, db_user, db_password, db_database):
    global last_report_id

    connection = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_database,
    )

    query = """
    SELECT
        d.fqdn AS domain_fqdn,
        r.org AS report_org,
        rr.dkim_align AS record_dkim_align,
        rr.spf_align AS record_spf_align,
        SUM(rr.rcount) AS total_rcount,
        r.id as id
    FROM
        reports r
    JOIN
        domains d ON r.domain_id = d.id
    JOIN
        rptrecords rr ON r.id = rr.report_id
    WHERE
        r.id >= %s
    GROUP BY
        r.id
    ORDER BY
        r.id ASC
    """

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, (last_report_id,))
            data = cursor.fetchall()

            for row in data:
                domain_fqdn, report_org, record_dkim_align, record_spf_align, total_rcount, last_report_id = row

                # Sum up new total_rcount
                if (domain_fqdn, report_org, record_dkim_align, record_spf_align) in new_state:
                    new_state[(domain_fqdn, report_org, record_dkim_align, record_spf_align)] += total_rcount
                else:
                    new_state[(domain_fqdn, report_org, record_dkim_align, record_spf_align)] = total_rcount

    finally:
        connection.close()

if __name__ == '__main__':

    # Parse the command line arguments
    parser = argparse.ArgumentParser(description='Prometheus exporter for dmarc-srg')
    parser.add_argument('db_host', help='MySQL database host')
    parser.add_argument('db_user', help='MySQL database user')
    parser.add_argument('db_password', help='MySQL database password')
    parser.add_argument('db_database', help='MySQL database name')
    parser.add_argument('--update-interval', type=int, default=15, help='Update interval in seconds (default: 15)')
    parser.add_argument('--port', type=int, default=10012, help='Listening port (default: 10012)')
    args = parser.parse_args()

    # Start the HTTP server to expose the metrics
    start_http_server(args.port)
    
    # Periodically fetch data from MySQL and update metrics
    while True:
        old_state = new_state
        new_state = {}

        fetch_and_update_metrics(
            args.db_host,
            args.db_user,
            args.db_password,
            args.db_database
        )

        # Update the Prometheus counter with the summed up total_rcount values
        for labels, value in new_state.items():

            if old_state.get(labels, 0) == value: continue

            domain_fqdn, report_org, record_dkim_align, record_spf_align = labels
            dmarc_srg_reports_total.labels(
                domain_fqdn=domain_fqdn,
                report_org=report_org,
                record_dkim_align=record_dkim_align,
                record_spf_align=record_spf_align
            ).inc(float(value))

        time.sleep(args.update_interval)
