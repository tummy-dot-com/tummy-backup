import sys
sys.path.append('/usr/local/lib/tummy-backup/www')
sys.path.append('/usr/local/lib/tummy-backup/www/lib')
sys.path.append('/usr/local/lib/tummy-backup/www/tummy-backup')

import controller, cherrypy

config, application = controller.setup_server()
cherrypy.engine.start(False)
#application = cherrypy.Application(Root(), script_name=None, config=None)
