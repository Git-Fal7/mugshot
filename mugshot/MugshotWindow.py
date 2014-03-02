#!/usr/bin/python3
# -*- Mode: Python; coding: utf-8; indent-tabs-mode: nil; tab-width: 4 -*-
#   Mugshot - Lightweight user configuration utility
#   Copyright (C) 2013-2014 Sean Davis <smd.seandavis@gmail.com>
#
#   This program is free software: you can redistribute it and/or modify it
#   under the terms of the GNU General Public License version 3, as published
#   by the Free Software Foundation.
#
#   This program is distributed in the hope that it will be useful, but
#   WITHOUT ANY WARRANTY; without even the implied warranties of
#   MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
#   PURPOSE.  See the GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License along
#   with this program.  If not, see <http://www.gnu.org/licenses/>.

from locale import gettext as _

import os
# Used for automating chfn
import pexpect
# Used for copying files to ~/.face
import shutil
# Used for which command and checking for running processes.
import subprocess
# DBUS interface is used to update pidgin buddyicon when pidgin is running.
import dbus

import tempfile

from gi.repository import Gtk, GdkPixbuf, GLib, Gio  # pylint: disable=E0611
import logging
logger = logging.getLogger('mugshot')

from mugshot_lib import Window
from mugshot.CameraMugshotDialog import CameraMugshotDialog

username = GLib.get_user_name()
home = GLib.get_home_dir()
libreoffice_prefs = os.path.join(GLib.get_user_config_dir(), 'libreoffice',
                            '4', 'user', 'registrymodifications.xcu')
pidgin_prefs = os.path.join(home, '.purple', 'prefs.xml')
faces_dir = '/usr/share/pixmaps/faces/'


def which(command):
    '''Use the system command which to get the absolute path for the given
    command.'''
    command = subprocess.Popen(['which', command],
                            stdout=subprocess.PIPE).stdout.read().strip()
    command = command.decode('utf-8')
    if command == '':
        logger.debug('Command "%s" could not be found.' % command)
        return None
    return command


def has_running_process(name):
    """Check for a running process, return True if any listings are found."""
    command = 'ps -ef | grep " %s" | grep -v "grep"  | wc -l' % name
    n = subprocess.Popen(command, stdout=subprocess.PIPE,
                                            shell=True).stdout.read().strip()
    return int(n) > 0


def has_gstreamer_camerabin_support():
    """Return True if gstreamer1.0 camerabin element is available."""
    process = subprocess.Popen(["gst-inspect-1.0", "camerabin"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    process.communicate()
    has_support = process.returncode == 0
    if not has_support:
        element = 'camerabin'
        plugin = 'gstreamer1.0-plugins-good'
        logger.debug('%s element unavailable. '
                     'Do you have %s installed?' % (element, plugin))
    return has_support


def has_gstreamer_camerasrc_support():
    """Return True if gstreamer1.0 v4l2src element is available."""
    process = subprocess.Popen(["gst-inspect-1.0", "v4l2src"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    process.communicate()
    has_support = process.returncode == 0
    if not has_support:
        element = 'v4l2src'
        plugin = 'gstreamer1.0-plugins-good'
        logger.debug('%s element unavailable. '
                     'Do you have %s installed?' % (element, plugin))
    return has_support


def get_camera_installed():
    """Return True if /dev/video0 exists."""
    if not os.path.exists('/dev/video0'):
        logger.debug('Camera not detected at /dev/video0')
        return False
    return True


def get_has_camera_support():
    """Return True if cameras are fully supported by this application."""
    if not get_camera_installed():
        return False
    if not which('gst-inspect-1.0'):
        return False
    if not has_gstreamer_camerabin_support():
        return False
    if not has_gstreamer_camerasrc_support():
        return False
    return True


def detach_cb(menu, widget):
    '''Detach a widget from its attached widget.'''
    menu.detach()


def get_entry_value(entry_widget):
    """Get the value from one of the Mugshot entries."""
    # Get the text from an entry, changing none to ''
    value = entry_widget.get_text().strip()
    if value.lower() == 'none':
        value = ''
    return value


def get_confirmation_dialog(parent, primary_message, secondary_message,
                                                                icon_name=None):
    """Display a confirmation (yes/no) dialog configured with primary and
    secondary messages, as well as a custom icon if requested."""
    dialog = Gtk.MessageDialog(transient_for=parent, flags=0,
                               message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.YES_NO,
                               text=primary_message)
    dialog.format_secondary_text(secondary_message)
    if icon_name:
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
        dialog.set_image(image)
    dialog.show_all()
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.YES


def menu_position(self, menu, data=None, something_else=None):
    '''Position a menu at the bottom of its attached widget'''
    widget = menu.get_attach_widget()
    allocation = widget.get_allocation()
    window_pos = widget.get_window().get_position()
    # Align the left side of the menu with the left side of the button.
    x = window_pos[0] + allocation.x
    # Align the top of the menu with the bottom of the button.
    y = window_pos[1] + allocation.y + allocation.height
    return (x, y, True)


# See mugshot_lib.Window.py for more details about how this class works
class MugshotWindow(Window):
    """Mugshot GtkWindow"""
    __gtype_name__ = "MugshotWindow"

    def finish_initializing(self, builder):  # pylint: disable=E1002
        """Set up the main window"""
        super(MugshotWindow, self).finish_initializing(builder)
        self.set_wmclass("Mugshot", "Mugshot")

        self.CameraDialog = CameraMugshotDialog

        # User Image widgets
        self.image_button = builder.get_object('image_button')
        self.user_image = builder.get_object('user_image')
        self.image_menu = builder.get_object('image_menu')
        self.image_menu.attach_to_widget(self.image_button, detach_cb)
        self.image_from_camera = builder.get_object('image_from_camera')
        image_from_stock = builder.get_object('image_from_stock')
        image_from_stock.set_visible(os.path.exists(faces_dir) and
                                       len(os.listdir(faces_dir)) > 0)

        # Entry widgets (chfn)
        self.first_name_entry = builder.get_object('first_name')
        self.last_name_entry = builder.get_object('last_name')
        self.initials_entry = builder.get_object('initials')
        self.office_phone_entry = builder.get_object('office_phone')
        self.home_phone_entry = builder.get_object('home_phone')
        self.email_entry = builder.get_object('email')
        self.fax_entry = builder.get_object('fax')

        # Stock photo browser
        self.stock_browser = builder.get_object('stock_browser')
        self.iconview = builder.get_object('stock_iconview')

        # File Chooser Dialog
        self.chooser = builder.get_object('filechooserdialog')
        self.crop_center = builder.get_object('crop_center')
        self.crop_left = builder.get_object('crop_left')
        self.crop_right = builder.get_object('crop_right')
        self.file_chooser_preview = builder.get_object('file_chooser_preview')
        # Add a filter for only image files.
        image_filter = Gtk.FileFilter()
        image_filter.set_name('Images')
        image_filter.add_mime_type('image/*')
        self.chooser.add_filter(image_filter)

        self.tmpfile = None

        # Populate all of the widgets.
        self.init_user_details()

    def init_user_details(self):
        """Initialize the user details entries and variables."""
        # Check for .face and set profile image.
        logger.debug('Checking for ~/.face profile image')
        face = os.path.join(home, '.face')
        if os.path.isfile(face):
            self.set_user_image(face)
        else:
            self.set_user_image(None)
        self.updated_image = None

        # Search /etc/passwd for the current user's details.
        logger.debug('Getting user details from /etc/passwd')
        for line in open('/etc/passwd', 'r'):
            if line.startswith(username + ':'):
                logger.debug('Found details: %s' % line.strip())
                details = line.split(':')[4]
                name, office, office_phone, home_phone = details.split(',', 3)
                break

        # Expand the user's fullname into first, last, and initials.
        try:
            first_name, last_name = name.split(' ', 1)
            initials = first_name[0] + last_name[0]
        except:
            first_name = name
            last_name = ''
            initials = first_name[0]

        # If the variables are defined as 'none', use blank for cleanliness.
        if home_phone == 'none':
            home_phone = ''
        if office_phone == 'none':
            office_phone = ''

        # Get dconf settings
        logger.debug('Getting initials, email, and fax from dconf')
        if self.settings['initials'] != '':
            initials = self.settings['initials']
        email = self.settings['email']
        fax = self.settings['fax']

        # Set the class variables
        self.first_name = first_name
        self.last_name = last_name
        self.initials = initials
        self.home_phone = home_phone
        self.office_phone = office_phone

        # Populate the GtkEntries.
        logger.debug('Populating entries')
        self.first_name_entry.set_text(self.first_name)
        self.last_name_entry.set_text(self.last_name)
        self.initials_entry.set_text(self.initials)
        self.office_phone_entry.set_text(self.office_phone)
        self.home_phone_entry.set_text(self.home_phone)
        self.email_entry.set_text(email)
        self.fax_entry.set_text(fax)

    # = Mugshot Window ======================================================= #
    def set_user_image(self, filename=None):
        """Scale and set the user profile image."""
        logger.debug("Setting user profile image to %s" % str(filename))
        if filename:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(filename)
            scaled = pixbuf.scale_simple(128, 128, GdkPixbuf.InterpType.HYPER)
            self.user_image.set_from_pixbuf(scaled)
        else:
            self.user_image.set_from_icon_name('avatar-default', 128)

    def filter_numbers(self, entry, *args):
        """Allow only numbers and + in phone entry fields."""
        text = entry.get_text().strip()
        entry.set_text(''.join([i for i in text if i in '+0123456789']))

    def on_apply_button_clicked(self, widget):
        """When the window Apply button is clicked, commit any relevant
        changes."""
        logger.debug('Applying changes...')
        if self.get_chfn_details_updated():
            self.save_chfn_details()

        if self.get_libreoffice_details_updated():
            self.set_libreoffice_data()

        if self.updated_image:
            self.save_image()

        self.save_gsettings()
        self.destroy()

    def save_gsettings(self):
        """Save details to dconf (the ones not tracked by /etc/passwd)"""
        logger.debug('Saving details to dconf: /apps/mugshot')
        self.settings.set_string('initials',
                                 get_entry_value(self.initials_entry))
        self.settings.set_string('email', get_entry_value(self.email_entry))
        self.settings.set_string('fax', get_entry_value(self.fax_entry))

    def entry_focus_next(self, widget):
        """Focus the next available entry when pressing Enter."""
        logger.debug('Entry activated, focusing next widget.')
        vbox = widget.get_parent().get_parent().get_parent().get_parent()
        vbox.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def on_cancel_button_clicked(self, widget):
        """When the window cancel button is clicked, close the program."""
        logger.debug('Cancel clicked, goodbye.')
        self.destroy()

    # = Image Button and Menu ================================================ #
    def on_image_button_clicked(self, widget):
        """When the menu button is clicked, display the photo menu."""
        if widget.get_active():
            logger.debug('Show photo menu')
            self.image_from_camera.set_visible(get_has_camera_support())
            self.image_menu.popup(None, None, menu_position,
                                        self.image_menu, 3,
                                        Gtk.get_current_event_time())

    def on_image_menu_hide(self, widget):
        """Untoggle the image button when the menu is hidden."""
        self.image_button.set_active(False)

    def on_camera_dialog_apply(self, widget, data=None):
        """Commit changes when apply is clicked."""
        self.updated_image = data
        self.set_user_image(data)

    def save_image(self):
        """Copy the updated image filename to ~/.face"""
        # Check if the image has been updated.
        if not self.updated_image:
            logger.debug('Photo not updated, not saving changes.')
            return False

        face = os.path.join(home, '.face')

        # If the .face file already exists, remove it first.
        logger.debug('Photo updated, saving changes.')
        if os.path.isfile(face):
            os.remove(face)

        # Copy the new file to ~/.face
        shutil.copyfile(self.updated_image, face)
        self.accounts_service_set_user_image(face)
        self.set_pidgin_buddyicon(face)
        self.updated_image = None
        return True

    def accounts_service_set_user_image(self, filename):
        """Set user profile image using AccountsService."""
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        result = bus.call_sync('org.freedesktop.Accounts',
                                '/org/freedesktop/Accounts',
                                'org.freedesktop.Accounts',
                                'FindUserByName',
                                GLib.Variant('(s)', (username,)),
                                GLib.VariantType.new('(o)'),
                                Gio.DBusCallFlags.NONE,
                                -1,
                                None)
        (path,) = result.unpack()

        bus.call_sync('org.freedesktop.Accounts',
                               path,
                               'org.freedesktop.Accounts.User',
                               'SetIconFile',
                               GLib.Variant('(s)', (filename,)),
                               GLib.VariantType.new('()'),
                               Gio.DBusCallFlags.NONE,
                               -1,
                               None)

    def set_pidgin_buddyicon(self, filename=None):
        """Sets the pidgin buddyicon to filename (usually ~/.face).

        If pidgin is running, use the dbus interface, otherwise directly modify
        the XML file."""
        if not os.path.exists(pidgin_prefs):
            logger.debug('Pidgin not installed or never opened, not updating.')
            return
        logger.debug('Prompting user to update pidgin buddy icon')
        update_pidgin = get_confirmation_dialog(self,
                    _("Update Pidgin buddy icon?"),
                    _("Would you also like to update your Pidgin buddy icon?"),
                    'pidgin')
        if update_pidgin:
            if has_running_process('pidgin'):
                self.set_pidgin_buddyicon_dbus(filename)
            else:
                self.set_pidgin_buddyicon_xml(filename)
        else:
            logger.debug('Reject: Not updating pidgin buddy icon')

    def set_pidgin_buddyicon_dbus(self, filename=None):
        """Set the pidgin buddy icon via dbus."""
        logger.debug('Updating pidgin buddy icon via dbus')
        bus = dbus.SessionBus()
        obj = bus.get_object("im.pidgin.purple.PurpleService",
                             "/im/pidgin/purple/PurpleObject")
        purple = dbus.Interface(obj, "im.pidgin.purple.PurpleInterface")
        # To make the change instantly visible, set the icon to none first.
        purple.PurplePrefsSetPath('/pidgin/accounts/buddyicon', '')
        if filename:
            purple.PurplePrefsSetPath('/pidgin/accounts/buddyicon', filename)

    def set_pidgin_buddyicon_xml(self, filename=None):
        """Set the buddyicon used by pidgin to filename (via the xml file)."""
        # This is hacky, but a working implementation for now...
        logger.debug('Updating pidgin buddy icon via xml')
        prefs_file = pidgin_prefs
        tmp_buffer = []
        if os.path.isfile(prefs_file):
            for line in open(prefs_file):
                if '<pref name=\'buddyicon\'' in line:
                    new = line.split('value=')[0]
                    if filename:
                        new = new + 'value=\'%s\'/>\n' % filename
                    else:
                        new = new + 'value=\'\'/>\n'
                    tmp_buffer.append(new)
                else:
                    tmp_buffer.append(line)
            write_prefs = open(prefs_file, 'w')
            for line in tmp_buffer:
                write_prefs.write(line)
            write_prefs.close()

    # = chfn functions ============================================ #
    def get_chfn_details_updated(self):
        """Return True if chfn-related details have been modified."""
        logger.debug('Checking if chfn details have been modified.')
        if self.first_name != self.first_name_entry.get_text().strip() or \
            self.last_name != self.last_name_entry.get_text().strip() or \
            self.home_phone != self.home_phone_entry.get_text().strip() or \
            self.office_phone != self.office_phone_entry.get_text().strip():
            logger.debug('chfn details have been modified.')
            return True
        logger.debug('chfn details have NOT been modified.')
        return False

    def save_chfn_details(self):
        """Commit changes to chfn-related details.  For full name, changes must
        be performed as root.  Other changes are done with the user password.

        Return exit codes for 1) full name changes and 2) home/work phone
        changes.

        e.g. [0, 0] (both passed)"""
        return_codes = []

        # Get the user's password
        password = self.get_password()
        if not password:
            return return_codes

        sudo = which('sudo')
        chfn = which('chfn')

        # Get each of the updated values.
        first_name = get_entry_value(self.first_name_entry)
        last_name = get_entry_value(self.last_name_entry)
        full_name = "%s %s" % (first_name, last_name)
        full_name = full_name.strip()
        office_phone = get_entry_value(self.office_phone_entry)
        if office_phone == '':
            office_phone = 'none'
        home_phone = get_entry_value(self.home_phone_entry)
        if home_phone == '':
            home_phone = 'none'

        # Full name can only be modified by root.  Try using sudo to modify.
        logger.debug('Attempting to set fullname with sudo chfn')
        child = pexpect.spawn('%s %s %s' % (sudo, chfn, username))
        child.timeout = 5
        try:
            child.expect([".*ssword.*", pexpect.EOF])
            child.sendline(password)
            child.expect(".*ame.*:")
            child.sendline(full_name)
            for i in range(5):
                child.sendline('')
        except pexpect.TIMEOUT:
            # Password was incorrect, or sudo rights not granted
            logger.debug('Timeout reached, password was incorrect or sudo '
                         'rights not granted.')
            pass
        child.close()
        if child.exitstatus == 0:
            self.first_name = first_name
            self.last_name = last_name
        return_codes.append(child.exitstatus)

        logger.debug('Attempting to set user details with chfn')
        child = pexpect.spawn(chfn)
        child.timeout = 5
        try:
            child.expect([".*ssword.*", pexpect.EOF])
            child.sendline(password)
            child.expect(['Room Number.*:', 'Office.*:'])
            child.sendline('')
            child.expect(['Work Phone.*:', 'Office Phone.*:'])
            child.sendline(office_phone)
            child.expect('Home Phone.*:')
            child.sendline(home_phone)
            child.sendline(home_phone)
        except pexpect.TIMEOUT:
            logger.debug('Timeout reached, password was likely incorrect.')
        child.close(True)
        if child.exitstatus == 0:
            self.office_phone = office_phone
            self.home_phone = home_phone
        return_codes.append(child.exitstatus)
        return return_codes

    # = LibreOffice ========================================================== #
    def get_libreoffice_details_updated(self):
        """Return True if LibreOffice settings need to be updated."""
        # Return False if there is no preferences file.
        if not os.path.isfile(libreoffice_prefs):
            logger.debug('LibreOffice is not installed or has not been opened.'
                         ' Not updating.')
            return False
        # Compare the current entries to the existing LibreOffice data.
        data = self.get_libreoffice_data()
        if data['first_name'] != get_entry_value(self.first_name_entry):
            return True
        if data['last_name'] != get_entry_value(self.last_name_entry):
            return True
        if data['initials'] != get_entry_value(self.initials_entry):
            return True
        if data['email'] != get_entry_value(self.email_entry):
            return True
        if data['home_phone'] != get_entry_value(self.home_phone_entry):
            return True
        if data['office_phone'] != get_entry_value(self.office_phone_entry):
            return True
        if data['fax'] != get_entry_value(self.fax_entry):
            return True
        logger.debug('LibreOffice details do not need to be updated.')
        return False

    def get_libreoffice_data(self):
        """Get each of the preferences from the LibreOffice registymodifications
        preferences file.

        Return a dict with the details."""
        prefs_file = libreoffice_prefs
        data = {'first_name': '', 'last_name': '', 'initials': '', 'email': '',
                'home_phone': '', 'office_phone': '', 'fax': ''}
        if os.path.isfile(prefs_file):
            logger.debug('Getting settings from %s' % prefs_file)
            for line in open(prefs_file):
                if "UserProfile/Data" in line:
                    try:
                        value = line.split('<value>')[1].split('</value>')[0]
                    except IndexError:
                        continue
                    value = value.strip()
                    # First Name
                    if 'name="givenname"' in line:
                        data['first_name'] = value
                    # Last Name
                    elif 'name="sn"' in line:
                        data['last_name'] = value
                    # Initials
                    elif 'name="initials"' in line:
                        data['initials'] = value
                    # Email
                    elif 'name="mail"' in line:
                        data['email'] = value
                    # Home Phone
                    elif 'name="homephone"' in line:
                        data['home_phone'] = value
                    # Office Phone
                    elif 'name="telephonenumber"' in line:
                        data['office_phone'] = value
                    # Fax Number
                    elif 'name="facsimiletelephonenumber"' in line:
                        data['fax'] = value
                    else:
                        pass
        return data

    def set_libreoffice_data(self):
        """Update the LibreOffice registymodifications preferences file."""
        prefs_file = libreoffice_prefs
        if os.path.isfile(prefs_file):
            logger.debug('Prompting user to update LibreOffice details.')
            update_libreoffice = get_confirmation_dialog(self,
                                _("Update LibreOffice user details?"),
                                _("Would you also like to update your user "
                                  "details in LibreOffice?"),
                                'libreoffice-startcenter')
            if update_libreoffice:
                logger.debug('Confirm: Updating details.')
                first_name = get_entry_value(self.first_name_entry)
                first_name_updated = False
                last_name = get_entry_value(self.last_name_entry)
                last_name_updated = False
                initials = get_entry_value(self.initials_entry)
                initials_updated = False
                email = get_entry_value(self.email_entry)
                email_updated = False
                home_phone = get_entry_value(self.home_phone_entry)
                home_phone_updated = False
                office_phone = get_entry_value(self.office_phone_entry)
                office_phone_updated = False
                fax = get_entry_value(self.fax_entry)
                fax_updated = False
                tmp_buffer = []
                for line in open(prefs_file):
                    new = None
                    if "UserProfile/Data" in line:
                        new = line.split('<value>')[0]
                        # First Name
                        if 'name="givenname"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        first_name
                            first_name_updated = True
                        # Last Name
                        elif 'name="sn"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        last_name
                            last_name_updated = True
                        # Initials
                        elif 'name="initials"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        initials
                            initials_updated = True
                        # Email
                        elif 'name="mail"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        email
                            email_updated = True
                        # Home Phone
                        elif 'name="homephone"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        home_phone
                            home_phone_updated = True
                        # Office Phone
                        elif 'name="telephonenumber"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        office_phone
                            office_phone_updated = True
                        # Fax Number
                        elif 'name="facsimiletelephonenumber"' in line:
                            new = new + '<value>%s</value></prop></item>\n' % \
                                        fax
                            fax_updated = True
                        else:
                            new = line
                        tmp_buffer.append(new)
                    elif '</oor:items>' in line:
                        pass
                    else:
                        tmp_buffer.append(line)
                open_prefs = open(prefs_file, 'w')
                for line in tmp_buffer:
                    open_prefs.write(line)

                if not first_name_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="givenname" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % first_name
                    open_prefs.write(string)
                if not last_name_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="sn" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % last_name
                    open_prefs.write(string)
                if not initials_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="initials" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % initials
                    open_prefs.write(string)
                if not email_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="mail" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % email
                    open_prefs.write(string)
                if not home_phone_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="homephone" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % home_phone
                    open_prefs.write(string)
                if not office_phone_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="telephonenumber" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % office_phone
                    open_prefs.write(string)
                if not fax_updated:
                    string = \
                    '<item oor:path="/org.openoffice.UserProfile/Data">'
                    '<prop oor:name="facsimiletelephonenumber" oor:op="fuse">'
                    '<value>%s</value></prop></item>\n' % fax
                    open_prefs.write(string)
                open_prefs.write('</oor:items>')
                open_prefs.close()
            else:
                logger.debug('Reject: Not updating.')

    # = Stock Browser ======================================================== #
    def on_image_from_stock_activate(self, widget):
        """When the 'Select image from stock' menu item is clicked, load and
        display the stock photo browser."""
        self.load_stock_browser()
        self.stock_browser.show_all()

    def load_stock_browser(self):
        """Load the stock photo browser."""
        # Check if the photos have already been loaded.
        model = self.iconview.get_model()
        if len(model) != 0:
            logger.debug("Stock browser already loaded.")
            return

        # If they have not, load each photo from faces_dir.
        logger.debug("Loading stock browser photos.")
        for filename in os.listdir(faces_dir):
            full_path = os.path.join(faces_dir, filename)
            if os.path.isfile(full_path):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(full_path)
                scaled = pixbuf.scale_simple(90, 90, GdkPixbuf.InterpType.HYPER)
                model.append([full_path, scaled])

    def on_stock_iconview_selection_changed(self, widget):
        """Enable stock submission only when an item is selected."""
        selected_items = self.iconview.get_selected_items()
        self.builder.get_object('stock_ok').set_sensitive(
                                                    len(selected_items) > 0)

    def on_stock_browser_delete_event(self, widget, event):
        """Hide the stock browser instead of deleting it."""
        widget.hide()
        return True

    def on_stock_cancel_clicked(self, widget):
        """Hide the stock browser when Cancel is clicked."""
        self.stock_browser.hide()

    def on_stock_ok_clicked(self, widget):
        """When the stock browser OK button is clicked, get the currently
        selected photo and set it to the user profile image."""
        selected_items = self.iconview.get_selected_items()
        if len(selected_items) != 0:
            # Get the filename from the stock browser iconview.
            path = int(selected_items[0].to_string())
            filename = self.iconview.get_model()[path][0]
            logger.debug("Selected %s" % filename)

            # Update variables and widgets, then hide.
            self.set_user_image(filename)
            self.updated_image = filename
            self.stock_browser.hide()

    def on_stock_iconview_item_activated(self, widget, path):
        """Allow selecting a stock photo with Enter."""
        self.on_stock_ok_clicked(widget)

    # = Image Browser ======================================================== #
    def on_image_from_browse_activate(self, widget):
        """Browse for a user profile image."""
        # Run the dialog, grab the filename if confirmed, then hide the dialog.
        response = self.chooser.run()
        if response == Gtk.ResponseType.APPLY:
            # Update the user image, store the path for committing later.
            if self.tmpfile and os.path.isfile(self.tmpfile.name):
                os.remove(self.tmpfile.name)
            self.tmpfile = tempfile.NamedTemporaryFile(delete=False)
            self.tmpfile.close()
            self.updated_image = self.tmpfile.name
            self.filechooser_preview_pixbuf.savev(self.updated_image, "png",
                                                                        [], [])
            logger.debug("Selected %s" % self.updated_image)
            self.set_user_image(self.updated_image)
        self.chooser.hide()

    def on_filechooserdialog_update_preview(self, widget):
        """Update the preview image used in the file chooser."""
        filename = widget.get_filename()
        if not filename:
            self.file_chooser_preview.set_from_icon_name('folder', 128)
            return
        if not os.path.isfile(filename):
            self.file_chooser_preview.set_from_icon_name('folder', 128)
            return
        filechooser_pixbuf = GdkPixbuf.Pixbuf.new_from_file(filename)

        # Get the image dimensions.
        height = filechooser_pixbuf.get_height()
        width = filechooser_pixbuf.get_width()
        start_x = 0
        start_y = 0

        if self.crop_center.get_active():
            # Calculate a balanced center.
            if width > height:
                start_x = (width - height) / 2
                width = height
            else:
                start_y = (height - width) / 2
                height = width

        elif self.crop_left.get_active():
            start_x = 0
            if width > height:
                width = height
            else:
                start_y = (height - width) / 2
                height = width
        elif self.crop_right.get_active():
            if width > height:
                start_x = width - height
                width = height
            else:
                start_y = (height - width) / 2
                height = width

        # Create a new cropped pixbuf.
        self.filechooser_preview_pixbuf = \
            filechooser_pixbuf.new_subpixbuf(start_x, start_y, width, height)

        scaled = self.filechooser_preview_pixbuf.scale_simple(128, 128,
                                                GdkPixbuf.InterpType.HYPER)
        self.file_chooser_preview.set_from_pixbuf(scaled)

    def on_crop_changed(self, widget, data=None):
        """Update the preview image when crop style is modified."""
        if widget.get_active():
            self.on_filechooserdialog_update_preview(self.chooser)

    # = Password Entry ======================================================= #
    def get_password(self):
        """Display a password dialog for authenticating to sudo and chfn."""
        logger.debug("Prompting user for password")
        dialog = self.builder.get_object('password_dialog')
        entry = self.builder.get_object('password_entry')
        response = dialog.run()
        dialog.hide()
        if response == Gtk.ResponseType.OK:
            logger.debug("Password entered")
            pw = entry.get_text()
            entry.set_text('')
            return pw
        logger.debug("Cancelled")
        return None

    def on_password_entry_changed(self, widget):
        """Enable password submission only when password is not blank."""
        self.builder.get_object('password_ok').set_sensitive(
                                                    len(widget.get_text()) > 0)
