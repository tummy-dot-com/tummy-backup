Clustered Backup Server
=======================

tummy-backup is as simple a possible, but no simpler.  The core of it is
based around simple, reliable routines: ZFS, rsync, cron+xargs for the
scheduler and parallel execution.  And at it's heart is a shell script
wrapping rsync that I've been refining since the '90s.

Following the Unix philosophy, it is quiet to indicate success, and makes
noise when there are problems.  It does include a fully-featured web
management interface, including backup browser and file/directory recovery.

ZFS does all the heavy lifting of managing historical data.  Unlike other
rsync-based backups, you won't fill the system with inodes or have duplicates
of large files that are appended to (log files, Zope databases, any journal
and most database files).

This is a backup system that was developed by tummy.com and has been in use
since 2010.  We have deployed it among a number of our consulting clients,
handling backups of between 5 and 200 servers.  It provides a central
management interface, so managing 1 backup server is as easy as managing 10.

tummy-backup has proven to be an extremely robust and reliable system
over the years.

It should work on any platform that has: rsync, ZFS, Python, and Postgres.

Installation
------------

I know some have deployed it to CentOS.  I don't currently have any CentOS
systems, so the only instructions I have for installing are for Ubuntu-like
OSes.  See the "INSTALL" files in this directory for Ubuntu 12.04 (also 16.04,
possibly 18.04), and Ubuntu 20.04 instructions.

Features
--------

* Web management interface.
* Space-efficient storage of deltas, deduplication and compression via ZFS.
* Secure backups using single-purpose SSH keys.
* Low maintenance: e-mail is only sent when attention is needed.
* Robust and reliable: Thousands of servers have been backed up for more
  than a decade.
* Clustered: Managing multiple backup servers is as easy as managing one.
