'''Example Seesaw pipeline.'''
from distutils.version import StrictVersion
import datetime
import hashlib
import os
import re
import socket
import shutil
import time
import sys

import seesaw
from seesaw.config import realize
from seesaw.externalprocess import WgetDownload, ExternalProcess
from seesaw.item import ItemInterpolation, ItemValue
from seesaw.pipeline import Pipeline
from seesaw.project import Project
from seesaw.task import SimpleTask, SetItemKey
from seesaw.tracker import PrepareStatsForTracker
from seesaw.util import find_executable


# check the seesaw version
if StrictVersion(seesaw.__version__) < StrictVersion("0.8.3"):
    raise Exception("This pipeline needs seesaw version 0.8.3 or higher.")


###########################################################################
# Find a useful Wpull executable.
#
# WPULL_EXE will be set to the first path that
# 1. does not crash with --version, and
# 2. prints the required version string
WPULL_EXE = find_executable(
    "Wpull",
    re.compile(r"\b1\.0\b"),
    [
        "./wpull",
        os.path.expanduser("~/.local/share/wpull-1.0/wpull"),
        os.path.expanduser("~/.local/bin/wpull"),
        "./wpull_bootstrap",
        "wpull",
    ]
)

if not WPULL_EXE:
    raise Exception("No usable Wpull found.")


###########################################################################
# The version number of this pipeline definition.
#
# Update this each time you make a non-cosmetic change.
# It will be added to the WARC files and reported to the tracker.
VERSION = "20150321.01"
USER_AGENT = 'ArchiveTeam'
TRACKER_ID = 'examplecity'
TRACKER_HOST = 'example.com.invalid'


###########################################################################
# This section defines project-specific tasks.
#
# Simple tasks (tasks that do not need any concurrency) are based on the
# SimpleTask class and have a process(item) method that is called for
# each item.


class CheckIP(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, "CheckIP")
        self._counter = 0

    def process(self, item):
        if self._counter <= 0:
            item.log_output('Checking IP address.')
            ip_set = set()

            ip_set.add(socket.gethostbyname('twitter.com'))
            ip_set.add(socket.gethostbyname('facebook.com'))
            ip_set.add(socket.gethostbyname('youtube.com'))
            ip_set.add(socket.gethostbyname('microsoft.com'))
            ip_set.add(socket.gethostbyname('icanhas.cheezburger.com'))
            ip_set.add(socket.gethostbyname('archiveteam.org'))

            if len(ip_set) != 6:
                item.log_output('Got IP addresses: {0}'.format(ip_set))
                item.log_output(
                    'You are behind a firewall or proxy. That is a big no-no!')
                raise Exception(
                    'You are behind a firewall or proxy. That is a big no-no!')

        # Check only occasionally
        if self._counter <= 0:
            self._counter = 10
        else:
            self._counter -= 1


class PrepareDirectories(SimpleTask):
    def __init__(self, warc_prefix):
        SimpleTask.__init__(self, "PrepareDirectories")
        self.warc_prefix = warc_prefix

    def process(self, item):
        item_name = item["item_name"]
        escaped_item_name = item_name.replace(':', '_').replace('/', '_')
        item['escaped_item_name'] = escaped_item_name

        dirname = "/".join((item["data_dir"], escaped_item_name))

        if os.path.isdir(dirname):
            shutil.rmtree(dirname)

        os.makedirs(dirname)

        item["item_dir"] = dirname
        item["warc_file_base"] = "%s-%s-%s" % (
            self.warc_prefix, escaped_item_name,
            time.strftime("%Y%m%d-%H%M%S")
        )

        open("%(item_dir)s/%(warc_file_base)s.warc.gz" % item, "w").close()


class MoveFiles(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, "MoveFiles")

    def process(self, item):
        # Check if wget was compiled with zlib support
        if os.path.exists("%(item_dir)s/%(warc_file_base)s.warc" % item):
            raise Exception('Please compile wget with zlib support!')

        os.rename("%(item_dir)s/%(warc_file_base)s.warc.gz" % item,
                  "%(data_dir)s/%(warc_file_base)s.warc.gz" % item)

        shutil.rmtree("%(item_dir)s" % item)


def get_hash(filename):
    with open(filename, 'rb') as in_file:
        return hashlib.sha1(in_file.read()).hexdigest()


CWD = os.getcwd()
PIPELINE_SHA1 = get_hash(os.path.join(CWD, 'pipeline.py'))
SCRIPT_SHA1 = get_hash(os.path.join(CWD, 'examplecity.py'))


def stats_id_function(item):
    # For accountability and stats.
    d = {
        'pipeline_hash': PIPELINE_SHA1,
        'script_hash': SCRIPT_SHA1,
        'python_version': sys.version,
        }

    return d


class WgetArgs(object):
    def realize(self, item):
        wget_args = [
            WPULL_EXE,
            "-nv",
            # "--user-agent", USER_AGENT,
            "--python-script", "examplecity.py",
            "-o", ItemInterpolation("%(item_dir)s/wpull.log"),
            "--no-check-certificate",
            "--database", ItemInterpolation("%(item_dir)s/wpull.db"),
            "--delete-after",
            "--no-robots",
            "--no-cookies",
            "--rotate-dns",
            # "--recursive", "--level=inf",
            "--recursive", "--level=2",
            "--no-parent",
            "--page-requisites",
            "--span-hosts-allow", "page-requisites,linked-pages",
            "--timeout", "30",
            "--tries", "2",
            "--wait", "0.5",
            "--random-wait",
            "--waitretry", "5",
            # "--domains", "example.com,example.net",
            # "--hostnames", "assets.cloudspeeder.invalid,cnd.wahoo.invalid",
            "--warc-file", ItemInterpolation("%(item_dir)s/%(warc_file_base)s"),
            "--warc-header", "operator: Archive Team",
            "--warc-header", "examplecity-dld-script-version: " + VERSION,
            "--warc-header", ItemInterpolation("examplecity-user: %(item_name)s"),
            ]

        domain = item['item_name']
        wget_args.append("http://{0}".format(domain))

        if 'bind_address' in globals():
            wget_args.extend(['--bind-address', globals()['bind_address']])
            print('')
            print('*** Wget will bind address at {0} ***'.format(
                globals()['bind_address']))
            print('')

        return realize(wget_args, item)


###########################################################################
# Initialize the project.
#
# This will be shown in the warrior management panel. The logo should not
# be too big. The deadline is optional.
project = Project(
    title="Example Seesaw Wpull Project",
    project_html="""
        <img class="project-logo" alt="Project logo" src="http://archiveteam.org/images/thumb/f/f1/Seesaw_figure.png/320px-Seesaw_figure.png" height="50px" title=""/>
        <h2>Example <span class="links"><a href="http://">Website</a> &middot;
            <a href="http://tracker.archiveteam.org/">Leaderboard</a></span></h2>
        <p>This is an example wpull project</p>
        <!--<p class="projectBroadcastMessage"></p>-->
    """,
    utc_deadline=datetime.datetime(2000, 1, 1, 23, 59, 0)
)

pipeline = Pipeline(
    CheckIP(),
    # GetItemFromTracker("http://%s/%s" % (TRACKER_HOST, TRACKER_ID), downloader,
    #                    VERSION),
    SetItemKey("item_name", "smaug.fart.website:8080"),
    PrepareDirectories(warc_prefix="examplecity"),
    WgetDownload(
        WgetArgs(),
        max_tries=2,
        accept_on_exit_code=[0, 4, 7, 8],
        env={
            "item_dir": ItemValue("item_dir"),
            "downloader": downloader
        }
    ),
    PrepareStatsForTracker(
        defaults={"downloader": downloader, "version": VERSION},
        file_groups={
            "data": [
                ItemInterpolation("%(item_dir)s/%(warc_file_base)s.warc.gz"),
            ]
        },
        id_function=stats_id_function,
        ),
    MoveFiles(),
    # LimitConcurrent(
    #     NumberConfigValue(min=1, max=4, default="1",
    #                       name="shared:rsync_threads", title="Rsync threads",
    #                       description="The maximum number of concurrent uploads."),
    #     UploadWithTracker(
    #         "http://%s/%s" % (TRACKER_HOST, TRACKER_ID),
    #         downloader=downloader,
    #         version=VERSION,
    #         files=[
    #             ItemInterpolation("%(data_dir)s/%(warc_file_base)s.warc.gz"),
    #         ],
    #         rsync_target_source_path=ItemInterpolation("%(data_dir)s/"),
    #         rsync_extra_args=[
    #             "--recursive",
    #             "--partial",
    #             "--partial-dir", ".rsync-tmp",
    #             ]
    #     ),
    # ),
    # SendDoneToTracker(
    #     tracker_url="http://%s/%s" % (TRACKER_HOST, TRACKER_ID),
    #     stats=ItemValue("stats")
    # )
    ExternalProcess("sleep", ["sleep", "60"]),
)
