Clustered Backup Server
=======================

This is a backup system that was developed by tummy.com and has been in use
since 2010.  We have deployed it among a number of our consulting clients,
handling backups of between 5 and 200 servers.  It provides a central
management interface, so managing 1 backup server is as easy as managing 10.

tummy-backup has proven to be an extremely robust and reliable system
over the years.

This software is a management interface using ZFS to do the "heavy lifting" of
data, either via ZFS-fuse or ZFS-on-Linux on Linux, or on FreeBSD.  ZFS
manages the deltas between incremental backups, deduplication, and data
replication and archiving.

It should work on any platform that has: rsync, ZFS, Python, and Postgres.

Features
--------

* Web management interface.
* Space-efficient storage of deltas, deduplication and compression via ZFS.
* Secure backups using single-purpose SSH keys.
* Low maintenance, e-mail is sent when attention is needed.
