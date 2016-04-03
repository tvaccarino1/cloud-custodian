import jmespath

from placebo import pill
import placebo

import json
import unittest
import os
import shutil
import zipfile

import boto3


class ZippedPill(pill.Pill):

    def __init__(self, path, prefix=None, debug=False):
        super(ZippedPill, self).__init__(prefix, debug)
        self.path = path
        self._used = set()
        self.archive = None

    def playback(self):
        self.archive = zipfile.ZipFile(self.path, 'r')
        self._files = set(self.archive.namelist())
        return super(ZippedPill, self).playback()        

    def record(self):
        self.archive = zipfile.ZipFile(self.path, 'a', zipfile.ZIP_DEFLATED)
        self._files = set([n for n in self.archive.namelist()
                           if n.startswith(self.prefix)])
        print self._files
        return super(ZippedPill, self).record()        

    def stop(self):
        super(ZippedPill, self).stop()
        if self.archive:
            self.archive.close()
        
    def save_response(self, service, operation, response_data,
                      http_response=200):
        filepath = self.get_new_file_path(service, operation)
        #pill.LOG.debug('save_response: path=%s', filepath)
        json_data = {'status_code': http_response,
                     'data': response_data}
        self.archive.writestr(
            filepath,
            json.dumps(json_data, indent=4, default=pill.serialize))

    def load_response(self, service, operation):
        response_file = self.get_next_file_path(service, operation)
        self._used.add(response_file)
        #pill.LOG.debug('load_responses: %s', response_file)
        response_data = json.loads(
            self.archive.read(response_file), object_hook=pill.deserialize)
        return (pill.FakeHttpResponse(response_data['status_code']),
                response_data['data'])

    def get_next_file_path(self, service, operation):
        base_name = '{0}.{1}'.format(service, operation)
        if self.prefix:
            base_name = '{0}.{1}'.format(self.prefix, base_name)
        #pill.LOG.debug('get_next_file_path: %s', base_name)
        next_file = None
        while next_file is None:
            index = self._index.setdefault(base_name, 1)
            fn = os.path.join(
                self._data_path, base_name + '_{0}.json'.format(index))
            if fn in self._files:
                next_file = fn
                self._index[base_name] += 1
            elif index != 1:
                self._index[base_name] = 1
            else:
                # we are looking for the first index and it's not here
                raise IOError('response file ({0}) not found'.format(fn))
        return fn

    
def attach(session, data_path, prefix=None, debug=False):
    pill = ZippedPill(data_path, prefix=prefix, debug=debug)
    pill.attach(session, prefix)
    return pill
    

class PillTest(unittest.TestCase):

    archive_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'placebo_data.zip')

    placebo_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'data', 'placebo')
    
    def assertJmes(self, expr, instance, expected):
        value = jmespath.search(expr, instance)
        self.assertEqual(value, expected)

    def cleanUp(self):
        pass
    
    def record_flight_data(self, test_case, zdata=False):
        if not zdata:
            test_dir = os.path.join(self.placebo_dir, test_case)
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir)
            os.makedirs(test_dir)

        session = boto3.Session()
        if not zdata:
            pill = placebo.attach(session, test_dir, debug=True)
        else:
            pill = attach(session, self.archive_path, test_case, debug=True)
            
        pill.record()
        self.addCleanup(pill.stop)
        self.addCleanup(self.cleanUp)
        # return session factory
        return lambda region=None, assume=None: session
    
    def replay_flight_data(self, test_case, zdata=False):
        if not zdata:
            test_dir = os.path.join(self.placebo_dir, test_case)
            if not os.path.exists(test_dir):
                raise RuntimeError(
                    "Invalid Test Dir for flight data %s" % test_dir)
        
        session = boto3.Session()
        if not zdata:
            pill = placebo.attach(session, test_dir)
        else:
            pill = attach(session, self.archive_path, test_case)
            
        pill.playback()
        self.addCleanup(pill.stop)
        self.addCleanup(self.cleanUp)
        return lambda region=None, assume=None: session
