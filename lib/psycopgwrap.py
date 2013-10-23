#!/usr/bin/env python
#
#  A wrapper around the psycopg2 code that makes some things easier.  For
#  example, returns are dictionaries, the "query" method creates and
#  automatically releases cursors.
#
#  You may also want to see Martin Blais' antiorm, which does some similar
#  things: http://furius.ca/antiorm/
#
#  Written by Sean Reifschneider <jafo@tummy.com>
#  Placed in the public domain.
#  No rights reserved.

'''
A wrapper around psycopg2 to make common things easier.

Examples:

    from psycopgwrap import Database as db
    db.connect('dbname=testdb')
    user = db.query('SELECT * FROM users WHERE name = %s', name)
    if user == None:
        print 'No such user "%s"' % name
    print 'User id: %s' % user['id']
    for row in db.query('SELECT * FROM ptinvoicestatus LIMIT 1'):
        print 'id:', row['id']
    for row in db.query('SELECT * FROM ptinvoicestatus WHERE id = %s', id):
        print 'id:', row['id']
    try:
        db.commit()
    except:
        db.rollback()
'''

from psycopg2 import ProgrammingError, IntegrityError  #  NOQA


###########################
class CursorHelper(object):
    ###########################
    def __init__(self, cursor):
        self.cursor = cursor
        self.currentRecord = None

    ###################
    def __iter__(self):
        while self.cursor.rownumber < self.cursor.rowcount:
            yield(self[self.cursor.rownumber])

    #############################
    def __getitem__(self, index):
        if index < 0:
            index = self.cursor.rowcount + index
        if index < self.cursor.rownumber - 1:
            raise NotImplementedError('Cannot get records except sequentially')
        while index >= self.cursor.rownumber:
            self.currentRecord = self.cursor.fetchone()
            if not self.currentRecord:
                raise IndexError('list index out of range')
        return(self.currentRecord)

    ##################
    def __del__(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None


###################
#  database wrapper
class DatabaseClass:
    ################
    def __init__(self):
        self.initialized = False
        self.connectString = None

    ##################
    def __del__(self):
        self.close()

    ########################################
    def connect(self, connectString=None):
        if connectString is None:
            from pgcredentials import connectString
        self.connectString = connectString
        self.setup()

    ################
    def setup(self):
        if self.initialized:
            return
        if not self.connectString:
            raise ValueError(
                'No connection string set, call '
                '"connection(connectString)" first.')

        from psycopg2.extras import DictConnection
        self.connection = DictConnection(self.connectString)
        self.initialized = True

    ################
    def close(self):
        if not self.initialized:
            return
        self.connection.close()
        self.connection = None
        self.initialized = False

    ##############################
    def query(self, query, *args):
        self.setup()
        cursor = self.connection.cursor()
        cursor.execute(query, args)
        return(CursorHelper(cursor))

    ##########################
    def queryone(self, *args):
        '''Like query(), but if you are expecting only one result.
        Either returns None if there were no results returned, or the row.
        '''
        try:
            ret = self.query(*args)[0]
        except IndexError:
            return(None)
        return(ret)

    #################
    def commit(self):
        self.setup()
        self.connection.commit()

    ###################
    def rollback(self):
        self.setup()
        self.connection.rollback()

Database = DatabaseClass()

##########################
if __name__ == '__main__':
    import sys
    import unittest

    if not 'test' in sys.argv:
        sys.stderr.write(
            'ERROR: You need to run with the "test" argument to '
            'run test suite\n')
        sys.exit(1)

    class testBase(unittest.TestCase):
        @classmethod
        def setUp(self):
            db = DatabaseClass()
            db.connect('dbname=template1')
            try:
                db.query('END')
                db.query('DROP DATABASE psycopgwraptest')
            except ProgrammingError:
                db.rollback()
            db.query('END')
            db.query('CREATE DATABASE psycopgwraptest')
            db.commit()
            self.db = DatabaseClass()
            self.db.connect('dbname=psycopgwraptest')
            self.db.query('CREATE TABLE indexes ( value INTEGER );')
            for i in xrange(100):
                self.db.query('INSERT INTO indexes ( value ) VALUES ( %s )', i)
            self.db.commit()

        def tearDown(self):
            self.db.close()
            db = DatabaseClass()
            db.connect('dbname=template1')
            db.query('END')
            db.query('DROP DATABASE psycopgwraptest')
            db.commit()

        def test_Indexes(self):
            db = self.db

            count = db.query("SELECT COUNT(*) FROM indexes")[0][0]
            self.assertEqual(count, 100)

            rows = db.query('SELECT * FROM indexes ORDER BY value')
            self.assertEqual(rows[0]['value'], 0)
            self.assertEqual(rows[0]['value'], 0)
            self.assertEqual(rows[1]['value'], 1)
            self.assertEqual(rows[2]['value'], 2)
            self.assertRaises(NotImplementedError, rows.__getitem__, 1)
            self.assertEqual(rows[-4]['value'], 96)
            self.assertEqual(rows[-3]['value'], 97)
            self.assertEqual(list(rows), [[98], [99]])

        def test_One(self):
            db = self.db
            self.assertEqual(
                db.queryone("SELECT * FROM indexes WHERE value = 10"),
                [10])
            self.assertEqual(
                db.queryone("SELECT * FROM indexes WHERE value = 1010"),
                None)

    suite = unittest.TestLoader().loadTestsFromTestCase(testBase)
    unittest.TextTestRunner(verbosity=2).run(suite)
