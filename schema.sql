\set ON_ERROR_STOP 1

CREATE TABLE config (
   id INTEGER UNIQUE DEFAULT 1,
   mail_to TEXT DEFAULT NULL,
   failure_warn INTERVAL DEFAULT '3 days' NOT NULL,
   rsync_timeout INTEGER DEFAULT 7200 NOT NULL,
   rsync_username TEXT DEFAULT 'root' NOT NULL,
   CHECK (id = 1)
   );
ALTER TABLE config OWNER TO tummybackup;

CREATE TABLE backupservers (
   id SERIAL UNIQUE NOT NULL,
   hostname TEXT UNIQUE NOT NULL,
   scheduler_slots INTEGER NOT NULL DEFAULT 6,
   backup_pool TEXT NOT NULL DEFAULT 'backups',
   backup_filesystem TEXT NOT NULL DEFAULT 'backups',
   backup_mountpoint TEXT NOT NULL DEFAULT '/backups',
   ssh_supports_y BOOLEAN DEFAULT 't'
   );
ALTER TABLE backupservers OWNER TO tummybackup;

CREATE TABLE hosts (
   id SERIAL UNIQUE NOT NULL,
   hostname TEXT UNIQUE,  -- NULL for default settings
   ipaddress TEXT DEFAULT NULL,  -- NULL indicates to use the hostname
   backupserver_id INTEGER NOT NULL
         REFERENCES backupservers(id) ON DELETE CASCADE ON UPDATE CASCADE,
   active BOOLEAN NOT NULL DEFAULT 'y',
   use_global_excludes BOOLEAN NOT NULL DEFAULT 'y',
   ping_minutes INTEGER DEFAULT NULL,
   retain_daily INTEGER DEFAULT 14,
   retain_weekly INTEGER DEFAULT 14,
   retain_monthly INTEGER DEFAULT 14,
   priority INTEGER DEFAULT 5 NOT NULL,
   window_start_time TIME WITHOUT TIME ZONE DEFAULT '22:00',
   window_end_time TIME WITHOUT TIME ZONE DEFAULT '05:00',
   next_backup TIMESTAMP DEFAULT NULL,
   backup_frequency INTERVAL NOT NULL DEFAULT '1 day',
   failure_warn INTERVAL DEFAULT NULL,
   space_used_snapshots NUMERIC DEFAULT NULL,
   space_used_dataset NUMERIC DEFAULT NULL,
   space_compression_ratio REAL DEFAULT NULL,
   rsync_bwlimit INTEGER DEFAULT NULL,
   rsync_do_compress BOOLEAN DEFAULT 'f' NOT NULL,
   rsync_checksum_frequency INTERVAL DEFAULT '1 month'  -- NULL for do not checksum
   );
ALTER TABLE hosts OWNER TO tummybackup;

CREATE TABLE backups (
   id SERIAL UNIQUE NOT NULL,
   host_id INTEGER NOT NULL
         REFERENCES hosts(id) ON DELETE CASCADE ON UPDATE CASCADE,
   backupserver_id INTEGER NOT NULL
         REFERENCES backupservers(id) ON DELETE CASCADE ON UPDATE CASCADE,
   start_time TIMESTAMP NOT NULL DEFAULT NOW(),
   end_time TIMESTAMP DEFAULT NULL,
   backup_pid INTEGER,  -- NULL indicates process no longer running
   generation TEXT NOT NULL CHECK (
      generation = 'daily'
      OR generation = 'weekly'
      OR generation = 'monthly'
   ),
   successful BOOLEAN DEFAULT NULL,  -- NULL means unknown
   was_checksum BOOLEAN NOT NULL,
   rsync_returncode INTEGER DEFAULT NULL,  -- NULL means unknown
   snapshot_name TEXT NOT NULL
   );
ALTER TABLE backups OWNER TO tummybackup;

CREATE TABLE excludes (
   id SERIAL UNIQUE NOT NULL,
   host_id INTEGER DEFAULT NULL
         REFERENCES hosts(id) ON DELETE CASCADE ON UPDATE CASCADE,
   priority INTEGER DEFAULT 5 NOT NULL,
   rsync_rule TEXT NOT NULL
   );
ALTER TABLE excludes OWNER TO tummybackup;

CREATE TABLE backupusage (
   id SERIAL UNIQUE NOT NULL,
   host_id INTEGER DEFAULT NULL
         REFERENCES hosts(id) ON DELETE CASCADE ON UPDATE CASCADE,
   sample_date DATE DEFAULT NULL,
   used_by_dataset BIGINT NOT NULL,
   used_by_snapshots BIGINT NOT NULL,
   compress_ratio_pct SMALLINT NOT NULL,
   backup_minutes SMALLINT,
   UNIQUE(host_id, sample_date)
   );
ALTER TABLE backupusage OWNER TO tummybackup;

CREATE TABLE serverusage (
   id SERIAL UNIQUE NOT NULL,
   server_id INTEGER DEFAULT NULL
         REFERENCES backupservers(id) ON DELETE CASCADE ON UPDATE CASCADE,
   sample_date DATE DEFAULT NULL,
   total_bytes BIGINT NOT NULL,
   free_bytes BIGINT NOT NULL,
   used_bytes BIGINT NOT NULL,
   usage_pct SMALLINT NOT NULL,
   dedup_ratio SMALLINT NOT NULL,
   UNIQUE(server_id, sample_date)
   );
ALTER TABLE serverusage OWNER TO tummybackup;

CREATE TABLE users (
   id SERIAL UNIQUE NOT NULL,
   name TEXT UNIQUE NOT NULL,
   cryptedpassword TEXT  -- NULL for login not allowed
   );
ALTER TABLE users OWNER TO tummybackup;
