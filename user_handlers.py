import logging
import os.path

from google.appengine.api import images
from google.appengine.api.images import NotImageError
from google.appengine.ext.webapp import template
import webapp2
from webapp2_extras import auth
from webapp2_extras import sessions
from webapp2_extras.auth import InvalidAuthIdError
from webapp2_extras.auth import InvalidPasswordError
from webapp2_extras.appengine.auth.models import User
from google.appengine.api import urlfetch

from models import Avatar

__author__ = 'Artem'


def user_required(handler):
    def check_login(self, *args, **kwargs):
        auth = self.auth
        if not auth.get_user_by_session():
            self.redirect(self.uri_for('login'), abort=True)
        else:
            return handler(self, *args, **kwargs)

    return check_login


class BaseHandler(webapp2.RequestHandler):
    @webapp2.cached_property
    def auth(self):
        return auth.get_auth()

    @webapp2.cached_property
    def user_info(self):
        return self.auth.get_user_by_session()

    @webapp2.cached_property
    def user(self):
        u = self.user_info
        return self.user_model.get_by_id(u['user_id']) if u else None

    @webapp2.cached_property
    def user_model(self):
        return self.auth.store.user_model

    @webapp2.cached_property
    def session(self):
        return self.session_store.get_session(backend="datastore")

    def render_template(self, view_filename, params={}):
        user = self.user_info
        params['user'] = user
        path = os.path.join(os.path.dirname(__file__), 'views', view_filename)
        self.response.out.write(template.render(path, params))

    def display_message(self, message):
        params = {
            'message': message
        }
        self.render_template('message.html', params)

    def dispatch(self):
        self.session_store = sessions.get_store(request=self.request)

        try:
            webapp2.RequestHandler.dispatch(self)
        finally:
            self.session_store.save_sessions(self.response)


class MainHandler(BaseHandler):
    def get(self):
        self.render_template('home.html')


class SignupHandler(BaseHandler):
    def get(self):
        self.render_template('signup.html')

    def post(self):
        user_name = self.request.get('username')
        email = self.request.get('email')
        name = self.request.get('name')
        password = self.request.get('password')
        last_name = self.request.get('lastname')

        unique_properties = ['email_address']
        user_data = self.user_model.create_user(user_name,
                                                unique_properties,
                                                email_address=email, name=name, password_raw=password,
                                                last_name=last_name, verified=False)
        if not user_data[0]:  # user_data is a tuple
            self.display_message('Unable to create user for email %s because of \
        duplicate keys %s' % (user_name, user_data[1]))
            return

        user = user_data[1]
        user_id = user.get_id()

        token = self.user_model.create_signup_token(user_id)

        user.verified = True
        user.add_auth_id(email)
        user.put()

        self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
        self.redirect(self.uri_for('home'))


class LoginHandler(BaseHandler):
    def get(self):
        self.__serve_page()

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')
        try:
            u = self.auth.get_user_by_password(username, password, remember=True,
                                               save_session=True)
            self.redirect(self.uri_for('home'))
        except (InvalidAuthIdError, InvalidPasswordError) as e:
            logging.info('Login failed for user %s because of %s', username, type(e))
            self.__serve_page(True)

    def __serve_page(self, failed=False):
        username = self.request.get('username')
        params = {
            'username': username,
            'failed': failed
        }
        self.render_template('login.html', params)


class LogoutHandler(BaseHandler):
    def get(self):
        self.auth.unset_session()
        self.redirect(self.uri_for('home'))


class UploadImageHandler(BaseHandler):
    @user_required
    def post(self):
        user = self.user
        image = self.request.get('file')
        img = images.Image(image)
        if image and img:
            avatar = Avatar(full_size_image=image)
            avatar.put()
            user.user_avatar = avatar
            user.put()
            self.redirect(self.uri_for('home'))
        else:
            msg = "You selected no image, try again!"
            self.display_message(msg)


class ShowUserAvatarHandler(BaseHandler):
    @user_required
    def get(self):
        user = self.user
        self.response.headers['Content-Type'] = 'image/png'
        self.response.write(user.user_avatar.full_size_image)


class GetAvatarHandler(BaseHandler):
    def get(self):
        self.render_template('get_avatar.html')
        pass

    def post(self):
        user_email = self.request.get('user_email')
        size = self.request.get('size')
        user = User.get_by_auth_id(user_email)
        avatar_url = self.request.get('avatar_url')
        msg = 'Unfortunately, you did input neither valid user email, nor valid image url. Try input something else'
        img = None
        if user:
            img = images.Image(user.user_avatar.full_size_image)
        elif avatar_url:
            try:
                result = urlfetch.fetch(avatar_url)
                img = images.Image(result.content)
            except:
                pass

        if img:
            self.response.headers['Content-Type'] = 'image/jpeg'
            try:
                if not size:
                    thumbnail = img._image_data
                    self.response.write(thumbnail)
                else:
                    size = int(size)
                    img.resize(width=size, height=size)
                    img.im_feeling_lucky()
                    thumbnail = img.execute_transforms(output_encoding=images.JPEG)
                    self.response.write(thumbnail)
            except NotImageError:
                self.display_message(msg)
        else:
            self.display_message(msg)
