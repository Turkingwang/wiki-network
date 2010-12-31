#!/usr/bin/env python

##########################################################################
#                                                                        #
# This program is free software; you can redistribute it and/or modify   #
# it under the terms of the GNU General Public License as published by   #
# the Free Software Foundation; version 2 of the License.                #
#                                                                        #
# This program is distributed in the hope that it will be useful,        #
# but WITHOUT ANY WARRANTY; without even the implied warranty of         #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the           #
# GNU General Public License for more details.                           #
#                                                                        #
##########################################################################

from sonet.mediawiki import HistoryPageProcessor, \
                            get_translations, get_tags, \
                            explode_dump_filename, only_inserted_text
from sonet import lib
from django.utils.encoding import smart_str
import csv
import difflib
import sys
import logging
from sonet.timr import Timr


class HistoryRevisionsPageProcessor(HistoryPageProcessor):
    queue = None
    _skip = None
    _prev_text = ""
    get_talks = True
    get_articles = True

    def __init__(self, **kwargs):
        super(HistoryRevisionsPageProcessor, self).__init__(**kwargs)
        self.queue = []
        f = open(self.output, 'w')
        self._keys = ["timestamp", "lang", "title", "type", "text"]
        self.csv_writer = csv.DictWriter(f, fieldnames=self._keys,
                                         delimiter='\t', quotechar='"',
                                         quoting=csv.QUOTE_ALL)

    def flush(self):
        pages = [{'title': page['title'],
                  'lang': self.lang,
                  'timestamp': page['timestamp'],
                  'text': page['text'],
                  'type': page['type']} for page in self.queue]
        self.csv_writer.writerows(pages)
        self.queue = []

    def save(self):
        if self._text == None: # difflib doesn't like NoneType
            self._text = ""
        sm = difflib.SequenceMatcher(None, self._prev_text, self._text)
        self._prev_text = self._text
        page = {'title': smart_str(self._title),
                'lang': self.lang,
                'timestamp': self._date,
                'text': smart_str(only_inserted_text(sm)),
                'type': self._type}
        self.queue.append(page)

    def process_title(self, elem):
        self.delattr(("_counter", "_type", "_title", "_skip", "_date", "text"))
        self._skip = False
        a_title = elem.text.split(':')

        if len(a_title) == 1 and self.get_articles:
            self._type = 'normal'
            self._title = a_title[0]
        elif len(a_title) == 2 and a_title[0] == self.talkns and \
                self.get_talks:
            self._type = 'talk'
            self._title = a_title[1]
        else:
            self._skip = True

        if not self._skip:
            self._desired = self.is_desired(self._title)
            if not self._desired:
                self._skip = True
            else:
                logging.info('Start processing desired page %s (%s)' % \
                             (self._title, self._type))

    def process_timestamp(self, elem):
        if self._skip:
            return
        self._date = elem.text

    def process_text(self, elem):
        if self._skip:
            return
        self._text = elem.text
        self.save()

    def process_page(self, elem):
        self.count += 1
        if not self.count % 1000:
            logging.info(' ### Processed %d pages' % self.count)
        self.delattr(("text"))
        if not self._skip:
            with Timr('Flushing %s' % self._title):
                self.flush()
        self._skip = False

    def process_redirect(self, elem):
        # This class only considers pages that are in the desired file,
        # these pages must not be redirects
        self._skip = True
        raise ValueError("The page %s is a redirect. " % self._title + \
                         "Pages in the desired list must not be redirects.")


def main():
    import optparse
    p = optparse.OptionParser(
        usage="usage: %prog [options] input_file desired_list output_file")
    p.add_option('-t', '--type', action="store", dest="type", default="all",
                 help="Type of page to analize (content|talk|all)")
    p.add_option('-v', action="store_true", dest="verbose", default=False,
                 help="Verbose output (like timings)")
    opts, files = p.parse_args()
    if len(files) != 3:
        p.error("Wrong parameters")
    if opts.verbose:
        logging.basicConfig(stream=sys.stderr,
                            level=logging.DEBUG,
                            format='%(asctime)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')

    xml = files[0]
    desired_pages_fn = files[1]
    output = files[2]

    with open(desired_pages_fn, 'rb') as f:
        desired_pages = [l[0].decode('latin-1') for l in csv.reader(f)
                                        if l and not l[0][0] == '#']
    lang, _, _ = explode_dump_filename(xml)
    deflate, _lineno = lib.find_open_for_this_file(xml)

    if _lineno:
        src = deflate(xml, 51)
    else:
        src = deflate(xml)

    translation = get_translations(src)
    tag = get_tags(src, tags='page,title,revision,timestamp,text,redirect')
    src.close()
    src = deflate(xml)

    processor = HistoryRevisionsPageProcessor(tag=tag, lang=lang,
                                              output=output)
    processor.talkns = translation['Talk']
    if opts.type == 'talk':
        processor.get_articles = False
    elif opts.type == 'content':
        proessor.get_talks = False
    processor.set_desired(desired_pages)
    with Timr('Processing'):
        processor.start(src) ## PROCESSING
    processor.flush()


if __name__ == "__main__":
    """
    import cherrypy
    import dowser
    cherrypy.tree.mount(dowser.Root())
    cherrypy.config.update({
        'environment': 'embedded',
        'server.socket_port': 8080
    })
    cherrypy.engine.start()
    """
    main()
