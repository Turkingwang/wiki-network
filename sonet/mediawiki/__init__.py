# -*- coding: utf-8 -*-
##########################################################################
#                                                                        #
#  This program is free software; you can redistribute it and/or modify  #
#  it under the terms of the GNU General Public License as published by  #
#  the Free Software Foundation; version 2 of the License.               #
#                                                                        #
#  This program is distributed in the hope that it will be useful,       #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of        #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         #
#  GNU General Public License for more details.                          #
#                                                                        #
##########################################################################

import re
import sys
from socket import inet_ntoa, inet_aton, error
from urllib import urlopen
from collections import namedtuple
import logging

from pageprocessor import PageProcessor, HistoryPageProcessor

try:
    import json
except ImportError:
    import simplejson as json


def fast_iter(context, func):
    """
    Use this function with etree.iterparse().

    See http://www.ibm.com/developerworks/xml/library/x-hiperfparse/ for doc.
    """
    for _, elem in context:
        func(elem)
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
    del context


def isip(s):
    """
    >>> isip("192.168.1.1")
    True
    >>> isip("not-an-ip")
    False
    """
    try:
        return inet_ntoa(inet_aton(s)) == s
    except error:
        return False


def isSoftRedirect(rawWikiText):
    r"""
    Find if the page starts with a soft redirect template

    >>> isSoftRedirect("{{softredirect|User:bot}}")
    True
    >>> isSoftRedirect("\n\n{{\nsoftredirect \n |  :en:User talk:bot}}")
    True
    >>> isSoftRedirect("{{ softredirect}}")
    False
    >>> isSoftRedirect("some text {{softredirect|:en:User talk:bot}}")
    False
    """
    rex = r'^[\n ]*{{[\n ]*softredirect[\n ]*\|[^}\n]*\}\}'
    return re.match(rex, rawWikiText) is not None

def is_archive(pagetitle):
    """
    Test whether a page is an archive or not
    (i.e. it contains a '/' in its title

    >>> is_archive('7_July_2005_London_bombings')
    False
    >>> is_archive('7_July_2005_London_bombings/Archive_2')
    True
    >>> is_archive('7_July_2005_London_bombings\/Archive_2')
    True
    >>> is_archive('7_July_2005_London_bombings/Archive_2/Some/thing/else')
    True
    """
    return bool(pagetitle.count('/'))

def isHardRedirect(rawWikiText):
    """
    >>> isHardRedirect("   #REDIRECT [[User:me]]")
    True
    >>> isHardRedirect("[[User:me]]")
    False
    """
    rex = r'[\n ]*#REDIRECT[\n ]*\[\[[^]]*\]\]'
    return re.match(rex, rawWikiText) is not None

class SignatureFinder(object):
    re = None
    def __init__(self, user_aliases, lang=None, signature='Sig'):
        self.user_aliases = user_aliases
        self.lang = lang
        self.signature = signature
        self.update_re()

    def update_re(self):
        search = self.user_aliases
        if self.lang:
            search += tuple([":%s:%s" % (self.lang, s) for s in search])
        rex = (
            r'\[\[(?:%(user_aliases)s):([^/]*?)[|\]][^\]]*\]'
            +r'|\{\{(?:%(user_aliases)s):([^/]*?)/%(sig)s\}\}'
            ) % {
                'user_aliases': '|'.join(search),
                'sig': self.signature
            }
        self.re = re.compile(rex, re.IGNORECASE)

    def find(self, rawWikiText):
        matches = self.re.findall(rawWikiText)

        weights = dict()
        for u in matches:
            sender = ''.join(u)

            if not sender:
                logging.warn('getCollaborators: empty username found')
                continue
            sender = unicode(capfirst(sender.replace('_', ' ')))
            weights[sender] = weights.get(sender, 0) + 1

        return weights

## re_cache is a mutable, so it keeps state through function calls
## TODO: add a deprecation warning and move the doc into SignatureFinder
def getCollaborators(rawWikiText, search, lang=None, signature='Sig',
                     re_cache = {}):
    """
    Search for regular expression containing [[User:username|anchor text]] and
    count a new message from username to the owner of the page. It also works
    on localized versions of the wikipedia, for example in the Italian
    Wikipedia it searches for
    [[Utente:username|anchor text]]

    We choose to get [[User:username|anchor text]] and not the
    User_discussion:username link for the following reason: signatures can be
    personalized.

    We rely on policies for signatures in the different Wikipedias.
    In English Wikipedia, see
    http://en.wikipedia.org/wiki/Wikipedia:Signatures#Links "Signatures must
    include at least one internal link to your user page, user talk page, or
    contributions page; this allows other editors easy access to your talk
    page and contributions log. The lack of such a link is widely viewed as
    obstructive." In Italian wikipedia, see
    http://it.wikipedia.org/wiki/Aiuto:Personalizzare_la_firma#Personalizzare_la_firma
    "La firma deve sempre contenere un wikilink alla pagina utente e/o alla
    propria pagina di discussione."

    >>> getCollaborators( \
            'd [[User:you|mee:-)e/e]] d [[User:me]][[utente:me]]', \
                         ('Utente', 'User'))
    {u'Me': 2, u'You': 1}
    >>> getCollaborators('[[User:you', ('Utente', 'User'))
    {}
    >>> getCollaborators('[[Utente:me/archive|archive]]', ('Utente', 'User'))
    {}
    >>> getCollaborators('[[:vec:Utente:me|or you]]', ('Utente', 'User'), \
            'vec')
    {u'Me': 1}
    >>> getCollaborators('{{Utente:me/sig}}', ('Utente', 'User'), \
            'vec')
    {u'Me': 1}
    """
    finder = SignatureFinder(search, lang, signature)
    return finder.find(rawWikiText)

##TODO: add doctests
def getTemplates(rawWikiText):
    rex = '\{\{(\{?[^\}\|\{]*)'
    matches = re.finditer(rex, rawWikiText)

    weights = dict()
    for tm in matches:
        t = tm.group(1)
        weights[t] = weights.get(t, 0) + 1

    return weights


#def getWords(rawWikiText):
#    import nltk

def addGroupAttribute(g, lang, group='bot', edits_only=False):

    users = getUsersGroup(lang, group, edits_only)

    if not users:
        g.vs[group] = [None,]*len(g.vs)
        return

    for user in users:
        try:
            g.vs.select(username=user)[0][group] = True
        except IndexError:
            pass

    return

def getUsersGroup(lang, group='bot', edits_only=False):
    """
    getUsersGroup returns a list of users on the "lang" wikipedia belonging to
    group (role) "group". "group" should be one of:
      bot, sysop, bureaucrat, checkuser, reviewer, steward, accountcreator,
      import, transwiki, ipblock-exempt, oversight, founder, rollbacker,
      confirmed, autoreviewer, researcher, abusefilter
    edits_only: returns only users that edited at least one time
    """
    base_url = ('http://%s.wikipedia.org/w/api.php?action=query&list=allusers'+
           '&augroup=%s&aulimit=500&format=json') % (lang, group)

    if edits_only:
        base_url += '&auwitheditsonly'

    start, list_ = None, []
    while True:
        url = base_url +'&aufrom='+start if start is not None else base_url
        res = json.load(urlopen(url))

        try:
            list_.extend(user['name'].encode('utf-8')
                         for user in res['query']['allusers'])
        except KeyError:
            logging.warn('Group %s has errors or has no users' % group)
            return
        logging.info(len(list_))

        try:
            qc = res['query-continue']
        except KeyError:
            break
        start = qc['allusers']['aufrom']

    return list_

def addBlockedAttribute(g, lang):
    g.vs['blocked'] = [None,]*len(g.vs)
    url = base_url = ('http://%s.wikipedia.org/w/api.php?action=query&list='+
                      'blocks&bklimit=500&format=json') % ( lang, )

    start = None
    while True:
        if start:
            url = '%s&bkstart=%s' % (base_url, start)
        logging.info("BLOCKED USERS: url = %s" % url)
        res = json.load(urlopen(url))

        if not res.has_key('query') or not res['query']['blocks']:
            logging.info('No blocked users')
            return

        bk_list = []
        for block in res['query']['blocks']:
            if not block.has_key('user'):
                continue
            logging.info(block['user'].encode('utf-8'))
            try:
                bk_list.append(block['user'].encode('utf-8'))
            except IndexError:
                pass

        bk_vs = g.vs.select(username_in=bk_list)
        bk_vs['blocked'] = (True,)*len(bk_vs)

        try:
            qc = res['query-continue']
        except KeyError:
            break
        start = qc['blocks']['bkstart']

    return


def getTags(src, tags='page,title,revision,text'):
    # find namespace (eg: http://www.mediawiki.org/xml/export-0.3/)
    try:
        root = src.readline()
        ns = unicode(re.findall(r'xmlns="([^"]*)', root)[0])

        tag_prefix = u'{%s}' % (ns,)

        tag = {}
        for t in tags.split(','):
            tag[t] = tag_prefix + unicode(t)
    finally:
        src.seek(0)

    return tag


def getNamespaces(src):
    try:
        counter = 0
        namespaces = []

        while 1:
            line = src.readline()
            if not line: break
            keys = re.findall(r'<namespace key="(-?\d+)"[^>]*>([^<]*)</namespace>',
                              line)
            for key, ns in keys:
                namespaces.append((key, ns))

            counter += 1
            if counter > 40:
                break
    finally:
        src.seek(0)

    return namespaces


def getTranslations(src):
    namespaces = dict(getNamespaces(src))
    translation = {
        'Talk': namespaces['1'],
        'User': namespaces['2'],
        'User talk': namespaces['3'],
        'Wikipedia': namespaces['4']
    }

    return translation


def explode_dump_filename(fn):
    """
    >>> explode_dump_filename( \
            "/tmp/itwiki-20100218-pages-meta-current.xml.bz2")
    ('it', '20100218', '-pages-meta-current')
    """
    from os.path import split

    s = split(fn)[1] #filename with extension
    res = re.search('(.*?)wiki[\-]*-(\d{8})([^.]*)', s)
    return (res.group(1), res.group(2), res.group(3))


def capfirst(s):
    """
    Given a string, it returns the same string with the first letter capitlized

    >>> capfirst("test")
    'Test'
    """
    return s[0].upper() + s[1:]


def count_renames(lang):
    url = base_url = ('http://%s.wikipedia.org/w/api.php?action=query&list='+\
                      'logevents&letype=renameuser&lelimit=500&leprop='+ \
                      'title|type|user|timestamp|comment|details&format=json'
                      ) % ( lang, )
    counter = 0
    start = None
    while True:
        if start:
            url = '%s&lestart=%s' % (base_url, start)
        res = json.load(urlopen(url))

        if not res.has_key('query') or not res['query']['logevents']:
            logging.info('No logs')
            return

        counter += len(res['query']['logevents'])

        if res.has_key('query-continue'):
            start = res['query-continue']['logevents']['lestart']
        else:
            break

    return counter

Message = namedtuple('Message', 'time welcome')
