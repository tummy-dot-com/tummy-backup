#!/usr/bin/env python

import os
import sys
import time

sys.path.append('/usr/local/lib/tummy-backup/www/lib')
sys.path.append('/usr/local/lib/tummy-backup/lib')

import tbsupp

import cherrypy
import cherrypy.lib.auth_basic
from genshi.template import TemplateLoader
from formencode import Invalid, Schema, validators


emptyPng = (
    '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x03\x00\x00\x00'
    '\x03\x08\x02\x00\x00\x00\xd9J"\xe8\x00\x00\x00\x01sRGB\x00\xae\xce'
    '\x1c\xe9\x00\x00\x00\x14IDAT\x08\xd7c```\xf8\xff\xff?\x03\x9cB\xe1'
    '\x00\x00\xb3j\x0b\xf52-\x07\x95\x00\x00\x00\x00IEND\xaeB`\x82')

loader = TemplateLoader(
    os.path.join(os.path.dirname(__file__), 'templates'),
    auto_reload=True)


def dbconnect():
    from psycopgwrap import Database as db
    db.connect()
    return db


def db_close():
    from psycopgwrap import Database as db
    db.close()
cherrypy.tools.db_close = cherrypy.Tool('on_end_request', db_close)


def url(*args, **kwargs):
    if len(args) == 1 and len(kwargs) == 0 and type(args[0]) in (str, unicode):
        return cherrypy.url(args[0])
    else:
        import routes
        return cherrypy.url(routes.url_for(*args, **kwargs))


def flash_present():
    return 'flash' in cherrypy.session


def flash_get():
    data = cherrypy.session.get('flash')
    del(cherrypy.session['flash'])
    return data


def contextFromLocals(locals):
    from genshi.template import Context
    data = {
        'url': url, 'cherrypy': cherrypy,
        'current_dashboard': {},
        'current_config': {},
        'current_indexdetails': {},
        'current_newbackup': {},
        'host_menu': False,
        'flash_present': flash_present,
        'flash_get': flash_get, }
    for key, value in locals.items():
        if key.startswith('_'):
            continue
        if key == 'self':
            continue
        data[key] = value
    return(Context(**data))


def processform(validator, defaults, form, list_fields=[]):
    '''Simple form validator, see `sysconfig()` for example use.  Any field
    names listed in `list_fields` will always be converted to a list before
    processing.
    '''
    if cherrypy.request.method != 'POST':
        return {}, defaults

    #  convert fields that may be lists to always be lists
    for field in list_fields:
        if field in form and not isinstance(form[field], (tuple, list)):
            form[field] = (form[field], )

    try:
        return {}, validator.to_python(form)
    except Invalid, e:
        return e.unpack_errors(), form


def validateTime(s):
    import re
    if not re.match(r'^[0-9][0-9]:[0-9][0-9](:[0-9][0-9])?$', s):
        raise ValueError('Invalid time format.')
    return(s)


def validateExcludeRule(s):
    import re
    if not re.match(
            r'^(include|exclude|merge|dir-merge|merge|\+|1)\s+\S.*$', s):
        raise ValueError('Invalid exclude rule format.')
    return(s)


def validateHostname(s):
    import re
    if not re.match(r'^[-a-zA-Z0-9._]+$', s):
        raise ValueError('Invalid hostname.')
    return(s)


def validateFailureWarn(s):
    from psycopg2 import DataError
    db = dbconnect()
    if s == '':
        return None
    try:
        db.queryone("SELECT %s::INTERVAL", s)
    except DataError:
        raise ValueError(
            'Must be empty (to use default) '
            'or a PostgreSQL interval like "3 days".')
    return s


def validateServername(s):
    db = dbconnect()
    row = db.queryone(
        "SELECT COUNT(*) FROM backupservers WHERE hostname = %s", s)
    if row[0] != 1:
        raise ValueError('Invalid backup server name.')
    return(s)


class NewHostValidator(Schema):
    hostname = validators.Wrapper(
        validate_python=validateHostname, not_empty=True)
    servername = validators.Wrapper(
        validate_python=validateServername, not_empty=True)


class HostConfigValidator(Schema):
    from formencode.foreach import ForEach

    new_exclude_priority = ForEach(
        validators.Int(min=0, max=9, not_empty=True), convert_to_list=True)
    new_exclude_rule = ForEach(validators.Wrapper(
        validate_python=validateExcludeRule,
        not_empty=True), convert_to_list=True)

    use_global_excludes = validators.StringBoolean(if_missing=False)
    rsync_do_compress = validators.StringBoolean(if_missing=False)
    active = validators.StringBoolean(if_missing=False)
    rsync_bwlimit = validators.Int(not_empty=False, min=0)
    priority = validators.Int(not_empty=True, min=0, max=10)
    retain_daily = validators.Int(not_empty=True, min=0)
    retain_weekly = validators.Int(not_empty=True, min=0)
    retain_monthly = validators.Int(not_empty=True, min=0)
    window_start_time = validators.Wrapper(validate_python=validateTime)
    window_end_time = validators.Wrapper(validate_python=validateTime)
    failure_warn = validators.Wrapper(
        validate_python=validateFailureWarn, not_empty=False)


class SystemConfigValidator(Schema):
    mail_to = validators.Email()
    failure_warn = validators.Wrapper(
        validate_python=validateFailureWarn, not_empty=False)
    rsync_timeout = validators.Int(not_empty=True, min=60, max=160000)
    rsync_username = validators.String(
        not_empty=True, strip=True, min=1, max=40)


class Root(object):
    def __init__(self):
        pass

    @cherrypy.expose
    def index(self):
        current_dashboard = {'class': 'current'}

        db = dbconnect()

        hosts_needing_attention = tbsupp.getHostsNeedingAttention(db)

        hosts = list(db.query(
            "SELECT *, "
            " (SELECT COUNT(*) FROM backups "
            "WHERE host_id = hosts.id AND generation = 'daily' "
            "AND successful = 't') AS daily_count, "
            " (SELECT COUNT(*) FROM backups "
            "WHERE host_id = hosts.id AND generation = 'weekly' "
            "AND successful = 't') AS weekly_count, "
            " (SELECT COUNT(*) FROM backups "
            "WHERE host_id = hosts.id AND generation = 'monthly' "
            "AND successful = 't') AS monthly_count, "
            "(SELECT NOW() - MAX(start_time) FROM backups "
            "WHERE host_id = hosts.id "
            "AND successful = 't') AS last_backup "
            "FROM hosts "
            "ORDER BY hostname"))
        active_backups = list(db.query(
            "SELECT * FROM backups, hosts "
            "WHERE backups.backup_pid IS NOT NULL "
            "AND hosts.id = backups.host_id "
            "ORDER BY backups.start_time"))
        title = 'Tummy-Backup'

        graphdate = ''
        graphdatajs = ''
        graphdatajsmax = ''
        for row in db.query(
                "SELECT sample_date, AVG(usage_pct) AS usage_pct, "
                "MAX(usage_pct) as max_usage_pct "
                "FROM serverusage GROUP BY sample_date ORDER BY sample_date;"):
            graphdate += '"%s",' % row['sample_date'].strftime('%Y-%m-%d')
            graphdatajs += '%.1f,' % row['usage_pct']
            graphdatajsmax += '%.1f,' % row['max_usage_pct']
        graphdate += ''
        graphdatajs += ''
        graphdatajsmax += ''

        tmpl = loader.load('index.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def detailedindex(self):
        import tbsupp

        current_indexdetails = {'class': 'current'}

        db = dbconnect()

        hosts_needing_attention = tbsupp.getHostsNeedingAttention(db)

        hosts = list(db.query(
            "SELECT *, "
            " (SELECT COUNT(*) FROM backups "
            "WHERE host_id = hosts.id AND generation = 'daily' "
            "AND successful = 't') AS daily_count, "
            " (SELECT COUNT(*) FROM backups "
            "WHERE host_id = hosts.id AND generation = 'weekly' "
            "AND successful = 't') AS weekly_count, "
            " (SELECT COUNT(*) FROM backups "
            "WHERE host_id = hosts.id AND generation = 'monthly' "
            "AND successful = 't') AS monthly_count, "
            "(SELECT NOW() - MAX(start_time) FROM backups "
            "WHERE host_id = hosts.id "
            "AND successful = 't') AS last_backup "
            "FROM hosts "
            "ORDER BY hostname"))
        title = 'Detailed Index'

        tmpl = loader.load('index-detailed.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def sysconfig(self, **kwargs):
        db = dbconnect()

        title = 'Tummy-Backup Configuration'

        current_config = {'class': 'current'}

        config = db.queryone("SELECT * FROM config")

        errors, formdata = processform(SystemConfigValidator(), config, kwargs)

        if cherrypy.request.method == 'POST' and not errors:
            for field in [
                    'mail_to', 'failure_warn', 'rsync_timeout',
                    'rsync_username']:
                db.query(
                    "UPDATE config SET %s = %%s" % field, formdata[field])
            db.commit()

            cherrypy.session['flash'] = 'Settings saved successfully.'

            raise cherrypy.HTTPRedirect(url('/config'))

        tmpl = loader.load('sysconfig.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def hostsearch(self, **kwargs):
        db = dbconnect()
        hostname = kwargs['hostname']

        hosts = list(db.query(
            "SELECT hostname FROM hosts WHERE hostname ~* %s", hostname))

        #  redirect if only one match
        if len(hosts) == 1:
            raise cherrypy.HTTPRedirect(url(str(
                '/hosts/%s/' % hosts[0]['hostname'])))

        #  return search results page
        if len(hosts) > 1:
            title = 'Host Search: %s' % (hostname,)
            tmpl = loader.load('host-search-list.html')
            return tmpl.generate(contextFromLocals(locals())).render(
                'html', doctype='html')

        #  error page if not found
        title = 'No Hosts Found'
        cherrypy.response.status = 404
        tmpl = loader.load('host-search-notfound.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def host(self, hostname):
        db = dbconnect()

        title = 'Host %s' % hostname

        host = db.queryone("SELECT * FROM hosts WHERE hostname = %s", hostname)

        #  search for host if we didn't find an exact match above
        if not host:
            hosts = list(db.query(
                "SELECT hostname FROM hosts WHERE hostname ~* %s", hostname))

            #  redirect if only one match
            if len(hosts) == 1:
                raise cherrypy.HTTPRedirect(url(str(
                    '/hosts/%s/' % hosts[0]['hostname'])))

            #  return search results page
            if len(hosts) > 1:
                title = 'Host Search: %s' % (hostname,)
                tmpl = loader.load('host-search-list.html')
                return tmpl.generate(contextFromLocals(locals())).render(
                    'html', doctype='html')

            #  error page if not found
            title = 'No Hosts Found'
            cherrypy.response.status = 404
            tmpl = loader.load('host-search-notfound.html')
            return tmpl.generate(contextFromLocals(locals())).render(
                'html', doctype='html')

        server = db.queryone(
            "SELECT * from backupservers WHERE id = %s",
            host['backupserver_id'])
        backups = db.query(
            "SELECT backups.* FROM backups, hosts "
            "WHERE backups.host_id = hosts.id AND hosts.hostname = %s "
            "ORDER BY backups.id DESC", hostname)
        mostrecentbackup = db.queryone(
            "SELECT * FROM backups "
            "WHERE host_id = %s ORDER BY id DESC LIMIT 1", host['id'])
        from tbsupp import describe_rsync_exit_code  #  NOQA

        dategraphdatajs = ''
        datagraphdatajs = ''
        snapgraphdatajs = ''
        maxSize = 0
        for row in db.query(
                "SELECT "
                "sample_date, SUM(used_by_dataset) AS used_by_dataset, "
                "SUM(used_by_snapshots) AS used_by_snapshots "
                "FROM backupusage "
                "WHERE host_id = %s "
                "GROUP BY sample_date ORDER BY sample_date;", host['id']):
            dategraphdatajs += '"%s",' % (
                row['sample_date'].strftime('%Y-%m-%d'))
            datagraphdatajs += '%d,' % row['used_by_dataset']
            snapgraphdatajs += '%d,' % row['used_by_snapshots']
            total = row['used_by_snapshots'] + row['used_by_dataset']
            if total > maxSize:
                maxSize = total
        if datagraphdatajs == '[':
            dategraphdatajs = '"%s"' % time.strftime('%Y/%m/%d')
            datagraphdatajs = '0,'
            snapgraphdatajs = '0,'

        yticks = '['
        sizel = [
            [0, 'B'], [1024, 'KiB'], [1024 ** 2, 'MiB'], [1024 ** 3, 'GiB'],
            [1024 ** 4, 'TiB'], [1024 ** 5, 'PiB'], [1024 ** 6, 'EiB']]
        for size, ext in sizel:
            if maxSize >= size:
                order = size
                suffix = ext
        if maxSize > 0:
            val = float(maxSize) / float(order)
        else:
            val = 0
        tweak = 10
        rounding = 3
        deci = 1
        for testmax, testtweak, testround, testdeci in [
                [10, 1, 2, 0], [100, 0.1, 1, 0]]:
            if val >= testmax:
                tweak = testtweak
                rounding = testround
                deci = testdeci
        peak = (int(val * tweak) + rounding) / float(tweak)
        yticks += "[0, '0'],"
        yticks += "[%d,'%0.*f %s']," % (
            peak * order * 0.25, deci, peak * 0.25, suffix)
        yticks += "[%d,'%0.*f %s']," % (
            peak * order * 0.5, deci, peak * 0.5, suffix)
        yticks += "[%d,'%0.*f %s']," % (
            peak * order * 0.75, deci, peak * 0.75, suffix)
        yticks += "[%d,'%0.*f %s']," % (peak * order, deci, peak, suffix)
        yticks += ']'

        tmpl = loader.load('host.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def hostconfig(self, hostname, **kwargs):
        import datetime

        db = dbconnect()

        title = 'Configure Host %s' % (hostname,)
        now = datetime.datetime.now()

        host = db.queryone("SELECT * FROM hosts WHERE hostname = %s", hostname)
        if not host:
            title = 'Invalid Host'
            tmpl = loader.load('hostconfig-invalidhost.html')
            return tmpl.generate(contextFromLocals(locals())).render(
                'html', doctype='html')

        excludes = db.query(
            "SELECT * FROM excludes "
            "WHERE (host_id IS NULL AND %s::BOOLEAN) OR host_id = %s "
            "ORDER BY priority", host['use_global_excludes'], host['id'])

        #  strip off any trailing form list entries
        while (kwargs.get('new_exclude_priority')
                and not kwargs['new_exclude_priority'][-1]
                and kwargs.get('new_exclude_rule')
                and not kwargs['new_exclude_rule'][-1]):
            kwargs['new_exclude_priority'] = kwargs[
                'new_exclude_priority'][:-1]
            kwargs['new_exclude_rule'] = kwargs['new_exclude_rule'][:-1]
        if (not kwargs.get('new_exclude_priority')
                and not kwargs.get('new_exclude_rule')):
            if 'new_exclude_priority' in kwargs:
                del(kwargs['new_exclude_priority'])
            if 'new_exclude_rule' in kwargs:
                del(kwargs['new_exclude_rule'])

        errors, formdata = processform(
            HostConfigValidator(),
            dict(new_exclude_priority='', new_exclude_rule='', **dict(host)),
            dict([
                (key, kwargs[key]) for key in kwargs.keys()
                if not key.startswith('delete_')]),
            ['new_exclude_priority', 'new_exclude_rule'])

        if cherrypy.request.method == 'POST' and not errors:
            for field in [
                    'active', 'use_global_excludes', 'retain_daily',
                    'retain_weekly', 'retain_monthly', 'rsync_do_compress',
                    'rsync_bwlimit', 'priority',
                    'window_start_time', 'window_end_time', 'failure_warn']:
                db.query(
                    "UPDATE hosts SET %s = %%s WHERE id = %%s" % field,
                    formdata[field], host['id'])
            if (formdata['new_exclude_priority']
                    and formdata['new_exclude_rule']):

                for priority, rule in zip(
                        formdata['new_exclude_priority'],
                        formdata['new_exclude_rule']):
                    db.query(
                        "INSERT INTO excludes "
                        "( host_id, priority, rsync_rule ) "
                        "VALUES ( %s, %s, %s )", host['id'], priority, rule)

            deleteList = [
                int(x.split('_', 1)[1]) for x in kwargs.keys()
                if x.startswith('delete_')]
            for deleteId in deleteList:
                db.query(
                    "DELETE FROM excludes WHERE id = %s AND host_id = %s",
                    deleteId, host['id'])
            db.commit()

            output = tbsupp.runWebCmd(
                tbsupp.lookupBackupServer(db, clienthostname=hostname),
                'updatekey\0%s\n' % (hostname,))

            if output.template_error():
                cherrypy.session['flash'] = (
                    'Error saving settings: %s' % output.template_error())
            else:
                cherrypy.session['flash'] = 'Settings saved successfully.'

            raise cherrypy.HTTPRedirect('config')

        rules_data = []
        if 'new_exclude_rule' in errors or 'new_exclude_priority' in errors:
            import itertools
            rules_data = list(itertools.izip_longest(
                formdata.get('new_exclude_priority', []),
                errors.get('new_exclude_priority', []),
                formdata.get('new_exclude_rule', []),
                errors.get('new_exclude_rule', [])))

        tmpl = loader.load('hostconfig.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def hostdestroy(self, hostname, **kwargs):
        db = dbconnect()

        title = 'Destroy Host %s' % (hostname,)

        host = db.query("SELECT * FROM hosts WHERE hostname = %s", hostname)[0]

        if cherrypy.request.method == 'POST':
            output = tbsupp.runWebCmd(
                tbsupp.lookupBackupServer(db, clienthostname=hostname),
                'destroyhost\0%s\n' % (hostname,))

            if output.template_error():
                cherrypy.session['flash'] = (
                    'Error destroying host: %s' % output.template_error())

            raise cherrypy.HTTPRedirect(url('/'))

        tmpl = loader.load('hostdestroy.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def backupdestroy(self, hostname, backupid, **kwargs):
        db = dbconnect()

        title = 'Destroy Backup %s for %s' % (backupid, hostname)

        host = db.queryone("SELECT * FROM hosts WHERE hostname = %s", hostname)
        backup = db.queryone(
            "SELECT * FROM backups WHERE id = %s", backupid)

        if cherrypy.request.method == 'POST':
            output = tbsupp.runWebCmd(
                tbsupp.lookupBackupServer(db, backupid=backupid),
                'destroybackup\0%s\n' % (backupid,))

            if output.template_error():
                cherrypy.session['flash'] = (
                    'Error destroying backup: %s' % output.template_error())

            raise cherrypy.HTTPRedirect('..')

        tmpl = loader.load('backupdestroy.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def backupctl(self, hostname, action):
        db = dbconnect()

        command = 'startbackup'
        if action.startswith('Kill'):
            command = 'killbackup'

        output = tbsupp.runWebCmd(
            tbsupp.lookupBackupServer(db, clienthostname=hostname),
            '%s\0%s\n' % (command, hostname))

        #  wait for child to finish
        output.stdout.read()

        if output.template_error():
            cherrypy.session['flash'] = (
                'Error sending command: %s' % output.template_error())
        else:
            cherrypy.session['flash'] = (
                'Backup "%s" message sent' % command[:-6])

        raise cherrypy.HTTPRedirect('.')

    @cherrypy.expose
    def backuplogfiles(self, hostname, backupid, **kwargs):
        from genshi.core import Markup

        db = dbconnect()

        title = 'Logs for Backup %s of %s' % (backupid, hostname)

        output = tbsupp.runWebCmd(
            tbsupp.lookupBackupServer(db, backupid=backupid),
            'logfiles\0%s\n' % backupid)
        logfileoutput = Markup(output.stdout.read())
        webcmd_error = output.template_error()

        tmpl = loader.load('backuplogfiles.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def backupajax(self, hostname, backup, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'

        db = dbconnect()
        output = tbsupp.runWebCmd(
            tbsupp.lookupBackupServer(db, clienthostname=hostname),
            'fsbrowsejson\0%s\0%s\n' % (backup, kwargs['key']))

        return(output.persistent_stdout())

    @cherrypy.expose
    def backuprecover(self, hostname, backupid, **kwargs):
        db = dbconnect()

        title = 'Recovery %s for %s' % (backupid, hostname)

        if cherrypy.request.method == 'POST':
            import pickle
            try:
                import json
            except ImportError:
                import simplejson as json
            recoverylist = json.loads(kwargs['recoverylist'])

            db = dbconnect()

            output = tbsupp.runWebCmd(
                tbsupp.lookupBackupServer(db, backupid=backupid),
                ('createtar\0%s\n' % backupid) + pickle.dumps(recoverylist))

            filename = 'recovery-%s-%s.tar.gz' % (hostname, backupid)
            cherrypy.response.headers['Content-Type'] = 'application/x-tar'
            cherrypy.response.headers[
                'Content-Disposition'] = 'attachment; filename="%s"' % filename
            return output.persistent_stdout()

        tmpl = loader.load('backup-recovery.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def backup(self, hostname, backupid):
        db = dbconnect()

        title = 'Backup %s for %s' % (backupid, hostname)

        host = db.queryone("SELECT * FROM hosts WHERE hostname = %s", hostname)
        backup = db.queryone(
            "SELECT * FROM backups "
            "WHERE host_id = %s AND backups.id = %s ",
            host['id'], int(backupid))
        from tbsupp import describe_rsync_exit_code  #  NOQA

        tmpl = loader.load('backup.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def hostkeys(self, hostname):
        db = dbconnect()

        title = 'SSH Key for %s' % (hostname,)

        output = tbsupp.runWebCmd(
            tbsupp.lookupBackupServer(db, clienthostname=hostname),
            'hostkey\0%s\n' % hostname)
        key = output.stdout.read()
        webcmd_error = output.template_error()

        tmpl = loader.load('host-keys.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')

    @cherrypy.expose
    def newbackup(self, **kwargs):
        db = dbconnect()

        title = 'Backup New Host'

        current_newbackup = {'class': 'current'}

        errors, formdata = processform(
            NewHostValidator(), dict(hostname='', servername=''), kwargs)

        if cherrypy.request.method == 'POST' and not errors:
            db = dbconnect()

            output = tbsupp.runWebCmd(tbsupp.lookupBackupServer(
                db, backupservername=formdata['servername']),
                'newbackup\0%s\n' % formdata['hostname'])

            #  wait for child to finish
            output.stdout.read()

            if output.template_error():
                cherrypy.session['flash'] = (
                    'Error creating backup: %s' % output.template_error())

            raise cherrypy.HTTPRedirect(url(str(
                '/hosts/%s/config' % formdata['hostname'])))

        #  get list of servers and post-process elements
        backupservers = []
        for server in list(db.query("""SELECT backupservers.*,
                (SELECT usage_pct FROM serverusage
                    WHERE server_id = backupservers.id
                    ORDER BY id DESC LIMIT 1) AS usage_pct
                FROM backupservers ORDER BY hostname""")):
            data = {'usage_pct_string': '', 'selected': None}
            data.update(server)
            if server['usage_pct']:
                data['usage_pct_string'] = ' (%d%%)' % server['usage_pct']
            backupservers.append(data)

        #  select the element with the lowest usage
        try:
            min_usage = min([
                x['usage_pct'] for x in backupservers
                if x['usage_pct'] is not None])
            [x for x in backupservers if x['usage_pct'] == min_usage][0][
                'selected'] = True
        except ValueError:
            min_usage = None

        #  hide server list if there's only one server
        show_serverlist = {}
        if len(backupservers) == 1:
            show_serverlist = {'class': 'hidden'}

        tmpl = loader.load('newbackup.html')
        return tmpl.generate(contextFromLocals(locals())).render(
            'html', doctype='html')


def checkpassword(realm, user, passwd):
    import crypt

    db = dbconnect()
    data = db.query(
        'SELECT cryptedpassword FROM users '
        'WHERE name = %s AND cryptedpassword IS NOT NULL', user)
    if data:
        data = list(data)
    if not data or not data[0]:
        return(False)
    return data[0][0] == crypt.crypt(passwd, data[0][0])


def routes():
    root = Root()
    d = cherrypy.dispatch.RoutesDispatcher()
    mapper = d.mapper
    mapper.explicit = False
    mapper.minimization = False

    d.connect(
        'backup', r'/hosts/{hostname}/{backupid}/', root, action='backup')
    d.connect(
        'backuplogfiles', r'/hosts/{hostname}/{backupid}/logfiles', root,
        action='backuplogfiles')
    d.connect(
        'backupajax', r'/hosts/{hostname}/{backup}/ajax', root,
        action='backupajax')
    d.connect(
        'backuprecover', r'/hosts/{hostname}/{backupid}/recover', root,
        action='backuprecover')
    d.connect(
        'backupdestroy', r'/hosts/{hostname}/{backupid}/destroy', root,
        action='backupdestroy')
    d.connect('host', r'/hosts/{hostname}/', root, action='host')
    d.connect('hostsearch', r'/hostsearch', root, action='hostsearch')
    d.connect(
        'hostconfig', r'/hosts/{hostname}/config', root, action='hostconfig')
    d.connect(
        'hostdestroy', r'/hosts/{hostname}/destroy', root,
        action='hostdestroy')
    d.connect(
        'hostkeys', r'/hosts/{hostname}/keys', root, action='hostkeys')
    d.connect(
        'backupctrl', r'/hosts/{hostname}/backupctl', root, action='backupctl')
    d.connect('newbackup', r'/newbackup', root, action='newbackup')
    d.connect(
        'detailedindex', r'/index-detailed/', root, action='detailedindex')
    d.connect('sysconfig', r'/config', root, action='sysconfig')
    d.connect('index', r'/', root)

    return d


def config():
    # Some global configuration; note that this could be moved into a
    # configuration file

    cherrypy.config.update({
        'tools.encode.on': True,
        'tools.encode.encoding': 'utf-8',
        'tools.decode.on': True,
        'tools.trailing_slash.on': True,
        'tools.staticdir.root': os.path.abspath(os.path.dirname(__file__)),
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8080,
        'log.screen': False,
        'log.error_file': '/tmp/site.log',
        'environment': 'production',
        'show_tracebacks': True,
    })

    config = {
        '/': {
            'request.dispatch': routes(),
            'tools.auth_basic.on': True,
            'tools.auth_basic.realm': 'tummy-backup',
            'tools.auth_basic.checkpassword': checkpassword,
            'tools.db_close.on': True,
        },
        '/static': {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'static'
        },
    }
    return(config)


def setup_server():
    cfg = config()
    app = cherrypy.tree.mount(None, config=cfg)

    return (cfg, app)


if __name__ == '__main__':
    cfg = setup_server()[0]
    cfg.update({'log.screen': True})
    cherrypy.quickstart(config=cfg)
else:
    sys.stdout = sys.stderr
    cfg = config()

    cherrypy.config.update({
        'log.error_file': '/tmp/error.log',
    })
    #  basic auth is implemented in Apache, couldn't get it working here
    cfg['/']['tools.auth_basic.on'] = False

    cfg['/']['tools.sessions.on'] = True
    cfg['/']['tools.sessions.storage_type'] = 'file'
    cfg['/']['tools.sessions.storage_path'] = '/tmp/'
    cfg['/']['tools.sessions.timeout'] = 600    # in minutes

    application = cherrypy.Application(
        None, script_name='/tummy-backup', config=cfg)
