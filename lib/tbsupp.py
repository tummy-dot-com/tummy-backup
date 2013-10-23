'''
Supplemental Python routine library for tummy-backup.
'''

import os
import sys
from psycopgwrap import IntegrityError
import tbsupp


######################
def setupExceptHook():
    #################
    class ExceptHook:
        #################################################
        def __init__(self, useSyslog=1, useStderr=0):
            self.useSyslog = useSyslog
            self.useStderr = useStderr

        #######################################
        def __call__(self, etype, evalue, etb):
            import traceback
            import string
            tb = traceback.format_exception(*(etype, evalue, etb))
            tb = map(string.rstrip, tb)
            tb = string.join(tb, '\n')
            for line in string.split(tb, '\n'):
                if self.useSyslog:
                    from syslog import syslog
                    syslog(line)
                if self.useStderr:
                    sys.stderr.write(line + '\n')
    sys.excepthook = ExceptHook(useSyslog=1, useStderr=0)


###################################
def describe_rsync_exit_code(code):
    if code is None:
        return ''
    return_code_descriptions = {
        -4: '"Kill Backup" marked this as a dead backup',
        -3: 'tbclean marked this as a dead backup',
        -2: 'zfsharness received INT signal',
        -1: 'Unknown zfsharness failure',
        0: 'Success',
        1: 'Syntax or usage error',
        2: 'Protocol incompatibility',
        3: 'Errors selecting input/output files, dirs',
        4: 'Requested action not supported: an attempt was made to '
            'manipulate 64-bit files on a platform that cannot support '
            'them; or an option was specified that is supported by the '
            'client and not by the server.',
        5: 'Error starting client-server protocol',
        6: 'Daemon unable to append to log-file',
        10: 'Error in socket I/O',
        11: 'Error in file I/O',
        12: 'Error in rsync protocol data stream',
        13: 'Errors with program diagnostics',
        14: 'Error in IPC code',
        20: 'Received SIGUSR1 or SIGINT',
        21: 'Some error returned by waitpid()',
        22: 'Error allocating core memory buffers',
        23: 'Partial transfer due to error',
        24: 'Partial transfer due to vanished source files',
        25: 'The --max-delete limit stopped deletions',
        30: 'Timeout in data send/receive',
        35: 'Timeout waiting for daemon connection', }
    return return_code_descriptions.get(
        int(code), 'Unknown exit-code %s' % code)


#################################
def getHostsNeedingAttention(db):
    lastBackupSQL = (
        "SELECT MAX(start_time) FROM backups "
        "WHERE host_id = hosts.id AND successful = 't'")
    backupCountSQL = (
        "SELECT COUNT(*) FROM backups "
        "WHERE host_id = hosts.id AND successful = 't'")
    failureDaysSQL = (
        "CASE WHEN failure_warn IS NOT NULL "
        "THEN failure_warn "
        "ELSE (SELECT failure_warn FROM CONFIG) END")
    return(list(db.query(
        "SELECT *, "
        "(%s) AS last_backup, "
        "(%s) AS backup_count "
        "FROM hosts "
        "WHERE active = 't' AND ((%s) < now() - (%s) "
        "OR (%s) < 1) "
        "ORDER BY hostname"
        % (lastBackupSQL, backupCountSQL, lastBackupSQL, failureDaysSQL,
            backupCountSQL,))))


############################
def getThisBackupServer(db):
    return db.queryone(
        'SELECT * FROM backupservers WHERE hostname = %s', os.uname()[1])


################################
def mountSnapshot(db, snapshot):
    #  find the backup information
    if isinstance(snapshot, str) and snapshot.isdigit():
        snapshot = int(snapshot)
    if isinstance(snapshot, int):
        backup = db.queryone('SELECT * FROM backups WHERE id = %s', snapshot)
    else:
        backup = db.queryone(
            'SELECT * FROM backups WHERE snapshot_name = %s', snapshot)
    if not backup:
        raise ValueError('Unknown backup "%s"' % snapshot)
    host = db.queryone('SELECT * FROM hosts WHERE id = %s', backup['host_id'])

    #  Are we running on the right server?
    backupserver = getThisBackupServer(db)
    if backupserver['id'] != backup['backupserver_id']:
        raise ValueError(
            'ERROR: webcmd is running on the wrong server (%d, expected %d)'
            % (backupserver['id'], backup['backupserver_id']))

    #  Is it the most current one, but with no snapshot?
    snapshotFSName = '%s/%s@%s' % (
        backupserver['backup_filesystem'],
        host['hostname'], backup['snapshot_name'])
    fp = os.popen('zfs list -t snapshot "%s" 2>&1' % snapshotFSName, 'r')
    fp.read()
    ret = fp.close()
    if ret is not None:
        row = db.queryone(
            'SELECT MAX(id) FROM backups WHERE host_id = %s',
            backup['host_id'])
        if not row or row[0] != backup['id']:
            raise ValueError(
                'ERROR: No snapshot exists for this backup, '
                'but this backup is not the most recent.')
        return '%s/%s' % (
            backupserver['backup_mountpoint'], host['hostname'])

    #  Create snapshot file-system and clone snapshot
    if (not os.path.exists(
        '%s/%s/snapshots' % (backupserver['backup_mountpoint'],
                             host['hostname']))
            or os.system(
                'zfs list -t filesystem "%s/%s/snapshots" >/dev/null 2>&1'
                % (backupserver['backup_mountpoint'], host['hostname'])) != 0):
        os.system(
            'zfs create "%s/%s/snapshots"'
            % (backupserver['backup_filesystem'], host['hostname']))
    if not os.path.exists(
        '%s/%s/snapshots/%s' % (
            backupserver['backup_mountpoint'], host['hostname'],
            backup['snapshot_name'])):
        os.system(
            'zfs clone "%s/%s@%s" "%s/%s/snapshots/%s"' % (
                backupserver['backup_filesystem'], host['hostname'],
                backup['snapshot_name'], backupserver['backup_filesystem'],
                host['hostname'], backup['snapshot_name']))
    return '%s/%s/snapshots/%s' % (
        backupserver['backup_mountpoint'], host['hostname'],
        backup['snapshot_name'])


############################
def updateKey(db, hostname):
    backupserver = getThisBackupServer(db)

    if db.queryone(
            'SELECT COUNT(*) FROM hosts WHERE hostname = %s',
            hostname)[0] == 0:
        db.query(
            "INSERT INTO hosts ( hostname, backupserver_id ) "
            "VALUES ( %s, %s )", hostname, backupserver['id'])
        db.commit()
    host = db.queryone('SELECT * FROM hosts WHERE hostname = %s', hostname)

    hostDir = os.path.join(backupserver['backup_mountpoint'], hostname)
    keysDir = os.path.join(hostDir, 'keys')

    authorizedkeysFile = os.path.join(keysDir, 'authorized_keys')
    identityFile = os.path.join(keysDir, 'backup-identity')

    compressOption = host['rsync_do_compress'] and '--compress' or ''
    bwlimitOption = (
        host['rsync_bwlimit']
        and ('--bwlimit=%s' % host['rsync_bwlimit']) or '')

    os.system('ssh-keygen -t rsa -f "%s" -N ""' % (identityFile,))
    fp = open(identityFile + '.pub', 'r')
    identity = fp.readline().strip()
    fp.close()
    fp = open(authorizedkeysFile, 'w')
    fp.write(
        'no-pty,no-agent-forwarding,no-X11-forwarding,'
        'no-port-forwarding,command="rsync --server --sender -lHogDtpre.i '
        '%s %s --ignore-errors --numeric-ids --inplace . /" %s\n'
        % (compressOption, bwlimitOption, identity))
    fp.close()


##################################
def createNewBackup(db, hostname):
    backupserver = getThisBackupServer(db)

    if db.queryone(
            'SELECT COUNT(*) FROM hosts WHERE hostname = %s',
            hostname)[0] == 0:
        db.query(
            "INSERT INTO hosts ( hostname, backupserver_id ) "
            "VALUES ( %s, %s )", hostname, backupserver['id'])
        db.commit()

    hostDir = os.path.join(backupserver['backup_mountpoint'], hostname)
    if not os.path.exists(hostDir):
        os.system(
            'zfs create "%s/%s"' % (
                backupserver['backup_filesystem'], hostname))

    dataDir = os.path.join(hostDir, 'data')
    keysDir = os.path.join(hostDir, 'keys')
    logsDir = os.path.join(hostDir, 'logs')

    for dir in [keysDir, logsDir, dataDir]:
        if not os.path.exists(dir):
            os.mkdir(dir)
    os.chmod(dataDir, 0700)

    updateKey(db, hostname)


###########################
def hostDirs(db, hostname):
    ######################
    class AttrString(str):
        '''A string class that can also have additional attributes stored in
        it to collect them together into a single object.  These attributes
        are nothing special, just additional names within the object.'''
        def __init__(self, *args, **kwargs):
            return(str.__init__(*args, **kwargs))

    host = db.queryone('SELECT * FROM hosts WHERE hostname = %s', hostname)
    backupserver = db.queryone(
        "SELECT * FROM backupservers WHERE id = %s", host['backupserver_id'])
    hostDir = AttrString(
        os.path.join(backupserver['backup_mountpoint'], hostname))
    hostDir.keysDir = os.path.join(hostDir, 'keys')
    hostDir.dataDir = os.path.join(hostDir, 'data')
    hostDir.logsDir = os.path.join(hostDir, 'logs')
    hostDir.snapshotsDir = os.path.join(hostDir, 'snapshots')
    return(hostDir)


#######################################################
def runZfsDestroy(filesystem, args=tuple(), retries=0):
    import subprocess

    #  skip a file-system/snapshot that doesn't exist
    cmd = ('zfs', 'list', filesystem)
    pipe = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    stdout, stderr = pipe.communicate()

    if pipe.returncode != 0:
        return (0, '', '')

    while True:
        retries = retries - 1

        cmd = ('zfs', 'destroy') + args + (filesystem,)
        pipe = subprocess.Popen(
            cmd, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True)
        stdout, stderr = pipe.communicate()

        if pipe.returncode == 0 or retries <= 0:
            if stdout:
                sys.stdout.write(stdout)
            if stderr:
                #  "dataset is busy" happens sometimes and will get
                #  cleaned up later
                if 'dataset is busy' not in stderr:
                    sys.stderr.write(stderr)
            return pipe.returncode, stdout, stderr


############################################
def destroyHost(db, hostname, verbose=True):
    host = db.queryone("SELECT * FROM hosts WHERE hostname = %s", hostname)
    if not host:
        sys.stderr.write('ERROR: Unknown host "%s"\n' % hostname)
        sys.exit(1)

    backupserver = db.queryone(
        'SELECT * FROM backupservers WHERE hostname = %s', os.uname()[1])
    if backupserver['id'] != host['backupserver_id']:
        hostserver = db.queryone(
            "SELECT hostname FROM backupservers WHERE id = %s",
            host['backupserver_id'])[0]
        sys.stderr.write(
            'ERROR: Host "%s" is backed up on server %s\n'
            % (hostname, hostserver))
        sys.exit(1)

    hostDir = os.path.join(backupserver['backup_mountpoint'], hostname)
    snapsDir = os.path.join(hostDir, 'snapshots')

    #  delete the backup snapshots
    for backup in db.query(
            "SELECT * FROM backups WHERE host_id = %s", host['id']):
        destroyBackup(db, backup['id'], verbose)

    if os.path.exists(snapsDir):
        if verbose:
            print 'Destroying snapshots sub-filesystem'
            sys.stdout.flush()
        runZfsDestroy('%s/%s/snapshots' % (
            backupserver['backup_filesystem'], hostname), retries=6)

    if verbose:
        print 'Destroying backup host file-system'
        sys.stdout.flush()
    runZfsDestroy('%s/%s' % (
        backupserver['backup_filesystem'], hostname,), retries=6)

    db.query("DELETE FROM hosts WHERE hostname = %s", hostname)
    db.commit()


#######################
def lookupBackupServer(
        db, backupservername=None, backupid=None,
        clienthostname=None):
    if clienthostname is not None:
        return db.queryone(
            "SELECT backupservers.* FROM backupservers, hosts "
            "WHERE hosts.hostname = %s "
            "AND backupservers.id = hosts.backupserver_id",
            clienthostname)

    if backupid is not None:
        return db.queryone(
            "SELECT backupservers.* FROM backupservers, backups "
            "WHERE backups.id = %s "
            "AND backupservers.id = backups.backupserver_id",
            int(backupid))

    return db.queryone(
        "SELECT backupservers.* "
        "FROM backupservers "
        "WHERE backupservers.hostname = %s ", backupservername)


###########################################
def runWebCmd(backupserverrecord, command):
    import subprocess

    class SubprocessStillRunningError(Exception):
        '''The child process is still running when we don't expect it to be.'''
        pass

    class OutputClass:
        def __init__(self, pipe, sshcmd):
            self.stdout = pipe.stdout
            self.stderr = pipe.stderr
            self.pipe = pipe
            self.cmd = ' '.join(sshcmd)

        def persistent_stdout(self):
            stdout = self.stdout
            self.stdout = None
            return stdout

        def exitcode(self):
            if self.pipe.returncode is None:
                self.exit_stdout = pipe.stdout.read()
                self.exit_stderr = pipe.stderr.read()
                pipe.wait()

                if self.pipe.returncode is None:
                    raise SubprocessStillRunningError()

            return self.pipe.returncode

        def template_error(self):
            '''Return None if exitcode() is 0, or an error message otherwise.
            '''
            if self.exitcode() != 0:
                return ('webcmd call failed with exit code %d, expected 0.'
                        % self.exitcode())
            return None

        def __del__(self):
            if self.stdout:
                self.stdout.close()
                self.stdout = None
            if self.stderr:
                self.stderr.close()
                self.stderr = None

    sshcmd = [
        'ssh', '-i', '/usr/local/lib/tummy-backup/www/keys/identity',
        'root@%s' % backupserverrecord['hostname'],
        '/usr/local/lib/tummy-backup/sbin/webcmd']
    pipe = subprocess.Popen(
        sshcmd, stdout=subprocess.PIPE,
        stdin=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    pipe.stdin.write(command)
    pipe.stdin.close()

    return OutputClass(pipe, sshcmd)


##############################################
def destroyBackup(db, backupid, verbose=True):
    backup = db.queryone('SELECT * FROM backups WHERE id = %s', backupid)
    host = db.queryone('SELECT * FROM hosts WHERE id = %s', backup['host_id'])
    backupserver = db.queryone(
        'SELECT * FROM backupservers WHERE hostname = %s', os.uname()[1])

    #  destroy backup on remote server
    if backupserver['id'] != backup['backupserver_id']:
        #  remove backup on remote server
        backupserverrecord = db.queryone(
            "SELECT backupservers.* FROM backupservers, backups "
            "WHERE backups.id = %s "
            "AND backupservers.id = backups.backupserver_id",
            backupid)

        if verbose:
            print (
                'Destroying backup id=%(id)s snapshot=%(snapshot_name)s'
                % backup) + (
                ' on remote server=%s' % backupserverrecord['hostname'])
            sys.stdout.flush()

        tbsupp.runWebCmd(
            tbsupp.lookupBackupServer(db, backupid=backupid),
            'destroybackup\0%s\n' % (backupid,))
        return

    hostDir = os.path.join(backupserver['backup_mountpoint'], host['hostname'])
    snapsDir = os.path.join(hostDir, 'snapshots')

    snappath = os.path.join(snapsDir, backup['snapshot_name'])
    if os.path.exists(snappath):
        if verbose:
            print ('Destroying clone snapshot=%(snapshot_name)s' % backup)
            sys.stdout.flush()
        runZfsDestroy('%s/%s/snapshots/%s' % (
            backupserver['backup_filesystem'], host['hostname'],
            backup['snapshot_name']), retries=6)

    if verbose:
        print 'Destroying backup id=%(id)s snapshot=%(snapshot_name)s' % backup
        sys.stdout.flush()
    runZfsDestroy('%s/%s@%s' % (
        backupserver['backup_filesystem'], host['hostname'],
        backup['snapshot_name']), args=('-R',), retries=6)

    db.query("DELETE FROM backups WHERE id = %s", backup['id'])
    db.commit()


############################################
def clearDeadBackups(db, hostrecord=None):
    backupserver = getThisBackupServer(db)
    if hostrecord:
        backups = db.query(
            "SELECT * FROM backups "
            "WHERE host_id = %s AND backupserver_id = %s "
            "AND backup_pid IS NOT NULL",
            hostrecord['id'], backupserver['id'])
    else:
        backups = db.query(
            "SELECT * FROM backups "
            "WHERE backupserver_id = %s AND backup_pid IS NOT NULL",
            backupserver['id'])

    for backup in backups:
        try:
            os.kill(backup['backup_pid'], 0)
        except OSError:
            #  process does not exist
            db.query(
                "UPDATE backups SET backup_pid = NULL, successful = 'f', "
                "rsync_returncode = -4 WHERE id = %s", backup['id'])
            db.query(
                "UPDATE backups SET end_time = NOW() "
                "WHERE id = %s AND end_time IS NULL", backup['id'])
            db.commit()


###############################################
def update_usage_stats(db, backupserver, host):
    '''Get the backup usage information and put it in the database.'''

    fp = os.popen(
        "zfs get usedbydataset,usedbysnapshots,compressratio '%s'" %
        os.path.join(backupserver['backup_filesystem'], host['hostname']),
        'r')
    data = {}
    for line in fp.readlines():
        fields = line.strip().split()
        if fields[0] == 'NAME':
            continue

        if fields[2][-1] not in 'xKMGT':
            data[fields[1]] = float(fields[2])
        else:
            value = float(fields[2][:-1])
            data[fields[1]] = value * {
                'x': 100,
                'K': 1000,
                'M': 1000000,
                'G': 1000000000,
                'T': 1000000000000}[fields[2][-1]]
    fp.close()

    if ('usedbydataset' not in data or 'usedbysnapshots' not in data
            or 'compressratio' not in data):
        sys.stderr.write(
            'Missing item in data=%s for host %s\n'
            % (repr(data), host['hostname']))
        return

    row = db.queryone(
        "SELECT end_time, start_time FROM backups "
        "WHERE host_id = %s AND successful = 't' "
        "ORDER BY start_time DESC LIMIT 1", host['id'])
    if not row:
        elapsedminutes = 'U'
        elapsedminutesOrNone = None
    else:
        elapsed = row['end_time'] - row['start_time']
        elapsedminutes = (elapsed.days * 24 * 60) + (elapsed.seconds / 60)
        elapsedminutesOrNone = elapsedminutes
    data['backuplength'] = elapsedminutes

    db.query(
        "UPDATE hosts "
        "SET space_used_snapshots = %s, space_used_dataset = %s, "
        "space_compression_ratio = %s WHERE id = %s",
        data['usedbysnapshots'], data['usedbydataset'],
        data['compressratio'], host['id'])
    db.commit()

    usage_id = db.queryone(
        'SELECT id FROM backupusage WHERE host_id = %s '
        'AND sample_date = NOW()::DATE', host['id'])
    try:
        if usage_id is not None:
            db.query(
                "UPDATE backupusage "
                "SET used_by_dataset = %s, used_by_snapshots = %s, "
                "compress_ratio_pct = %s, backup_minutes = %s "
                "WHERE id = %s",
                data['usedbydataset'], data['usedbysnapshots'],
                data['compressratio'], elapsedminutesOrNone,
                usage_id['id'])
            db.commit()
        else:
            db.query(
                "INSERT INTO backupusage "
                "( host_id, sample_date, used_by_dataset, used_by_snapshots, "
                "compress_ratio_pct, backup_minutes ) "
                "VALUES ( %s, NOW(), %s, %s, %s, %s )",
                host['id'], data['usedbydataset'], data['usedbysnapshots'],
                data['compressratio'], elapsedminutesOrNone)
            db.commit()

    except IntegrityError:
        db.rollback()
