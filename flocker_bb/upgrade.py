from twisted.application.service import Service
from twisted.internet import reactor
from twisted.python import log
from buildbot.scripts.upgrade_master import upgradeDatabase, loadConfig

class UpgradeService(Service):

    def __init__(self, basedir, configFile, afterService):
	self.basedir = basedir
	self.configFile = configFile
	self.afterService = afterService

    def startService(self):
        upgradeConfig = {'basedir': self.basedir, 'quiet': True}
        masterConfig = loadConfig(upgradeConfig, self.configFile)
        d = upgradeDatabase(upgradeConfig, masterConfig)
	d.addCallback(lambda _: self.afterService.setServiceParent(self.parent))
        d.addErrback(log.err)
        d.addErrback(lambda _: reactor.stop())	
