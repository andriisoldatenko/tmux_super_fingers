# -*- coding: UTF-8 -*-

from functools import reduce
import operator
from pprint import pprint
import os
import re
import subprocess
from os.path import abspath
# from concurrent import futures
import curses
from curses import wrapper

PATTERN = re.compile(
    '(?P<rails_log_controller>(?:[A-Z]\\w*::)*[A-Z]\\w*Controller#\\w+)|'
    'Render(?:ed|ing) (?P<rails_log_partial>[-a-zA-Z0-9_+-,./]+)|'
    '(?P<url>(https?|tcp)://[-a-zA-Z0-9@:%._\\+~#=]{2,256}\\b([-a-zA-Z0-9@:%_\\+.~#?&/=]*))|'
    '\\+\\+\\+ b/?(?P<diff_path>([~./]?[-a-zA-Z0-9_+-,./]+(?::\\d+)?))|'
    '(?P<path>([~./]?[-a-zA-Z0-9_+-,./]+(?::\\d+)?))'
)

def compact(l):
    return [e for e in l if e]

def shell(command):
    return subprocess.run(
        command.split(' '),
        stdout=subprocess.PIPE,
        check=True
    ).stdout.decode('utf-8').rstrip()

def camel_to_snake(string):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', string)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def get_pane_data(pane_props):
    pane_id, pane_current_path, pane_left, pane_right, pane_top, pane_bottom = pane_props.split(',')
    return {
        'unwrapped_text': shell('tmux capture-pane -p -J -t ' + pane_id),
        'text': shell('tmux capture-pane -p -t ' + pane_id),
        'pane_current_path': pane_current_path,
        'pane_left': int(pane_left),
        'pane_right': int(pane_right),
        'pane_top': int(pane_top),
        'pane_bottom': int(pane_bottom),
    }

def get_panes():
    panes_props = shell(
        'tmux list-panes -t ! -F #{pane_id},#{pane_current_path},#{pane_left},#{pane_right},#{pane_top},#{pane_bottom}'
    ).split('\n')
    return map(get_pane_data, panes_props)

def find_match(m, text, path_prefix):
    start, end = m.span()
    mark_text = text[start:end].replace('\n', '').replace('\0', '')

    path_match = m.groupdict()['path']
    diff_path_match = m.groupdict()['diff_path']
    url_match = m.groupdict()['url']
    rails_controller_match = m.groupdict()['rails_log_controller']
    rails_partial_match = m.groupdict()['rails_log_partial']

    mark_data = {}

    if path_match or diff_path_match:
        if diff_path_match:
            start, end = m.span('diff_path')
            mark_text = text[start:end].replace('\n', '').replace('\0', '')

        parts = mark_text.rsplit(':', 1)
        file_path = parts[0]

        if file_path not in ('.', '..', '/'):
            file_path = abspath(os.path.join(path_prefix, file_path))
            if os.path.exists(file_path):
                mark_data = {'file_path': file_path}
                if len(parts) > 1:
                    mark_data['line_number'] = parts[1]

    elif rails_partial_match:
        start, end = m.span('rails_log_partial')
        mark_text = text[start:end].replace('\n', '').replace('\0', '')
        file_path = os.path.join(path_prefix, 'app/views/' + mark_text)

        if os.path.exists(file_path):
            mark_data = {
                'file_path': file_path
            }

    elif url_match:
        mark_data = {
            'url': mark_text.replace('tcp', 'http')
        }

    elif rails_controller_match:
        controller_class, action = mark_text.split('#')
        controller_path = 'app/controllers/' + '/'.join(
            map(camel_to_snake, controller_class.split('::'))
        ) + '.rb'
        controller_path = os.path.join(path_prefix, controller_path)

        method_def_regex = re.compile('^\\s*def\\s+%s' % (action))

        if os.path.exists(controller_path):
            mark_data = {'file_path': controller_path}

            with open(controller_path) as ruby_file:
                line_number = 0
                for line in ruby_file:
                    line_number += 1

                    if method_def_regex.match(line):
                        mark_data['line_number'] = line_number

    if mark_data:
        return {
            'start': start,
            'end': end,
            'mark_text': mark_text,
            'mark_data': mark_data
        }

def get_pane_marks(pane):
    marks = []
    path_prefix = pane['pane_current_path']
    text = pane['unwrapped_text']

    matches = re.finditer(PATTERN, text)

    # Concurrent map is actually _slower_ than a regular map.
    #
    # with futures.ThreadPoolExecutor() as executor:
    #     marks = compact(executor.map(lambda m: find_match(m, text, path_prefix), matches))

    marks = compact(map(lambda m: find_match(m, text, path_prefix), matches))
    pane['marks'] = marks

    return pane

def main(stdscr):
    panes = map(get_pane_marks, get_panes())
    # To inherit window background
    curses.use_default_colors()
    curses.curs_set(False)
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)

    for pane in panes:
        if pane['pane_top'] > 0:
            pane_width = pane['pane_right'] - pane['pane_left'] + 1
            stdscr.addstr(pane['pane_top'] - 1, pane['pane_left'], '─' * pane_width)

        if pane['pane_left'] > 0:
            pane_height = pane['pane_bottom'] - pane['pane_top'] + 1
            for ln in range(pane_height):
                stdscr.addstr(pane['pane_top'] + ln, pane['pane_left'] - 1, '│')

        for ln, line in enumerate(pane['text'].split('\n')):
            stdscr.addstr(pane['pane_top'] + ln, pane['pane_left'], line)


    # stdscr.addstr("Current mode: Typing mode\n", curses.A_BOLD)
    # stdscr.addstr("Current mode: Typing mode\n", curses.color_pair(1))
    # stdscr.addstr("Current mode: Typing mode\n", curses.color_pair(1) | curses.A_BOLD)
    # stdscr.addstr("Current mode: Typing mode\n", curses.A_DIM)
    stdscr.refresh()
    stdscr.getkey()

if __name__ == "__main__":
    wrapper(main)
