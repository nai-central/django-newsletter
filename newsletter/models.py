import logging
logger = logging.getLogger(__name__)

from django.db import models
from django.db.models import permalink

from django.template.loader import select_template

from django.utils.timezone import now

from django.core.mail import EmailMultiAlternatives

from django.contrib.sites.models import Site
from django.contrib.sites.managers import CurrentSiteManager

from django.conf import settings

from .utils import (
    make_activation_code, get_default_sites, ACTIONS
)

User = settings.AUTH_USER_MODEL


class Newsletter(models.Model):
    site = models.ManyToManyField(Site, default=get_default_sites)

    title = models.CharField(
        max_length=200, verbose_name='newsletter title'
    )
    slug = models.SlugField(db_index=True, unique=True)

    email = models.EmailField(
        verbose_name='e-mail', help_text='Sender e-mail'
    )
    sender = models.CharField(
        max_length=200, verbose_name='sender', help_text='Sender name'
    )

    visible = models.BooleanField(
        default=True, verbose_name='visible', db_index=True
    )

    send_html = models.BooleanField(
        default=True, verbose_name='send html',
        help_text='Whether or not to send HTML versions of e-mails.'
    )

    objects = models.Manager()

    # Automatically filter the current site
    on_site = CurrentSiteManager()

    def get_templates(self, action):
        """
        Return a subject, text, HTML tuple with e-mail templates for
        a particular action. Returns a tuple with subject, text and e-mail
        template.
        """

        assert action in ACTIONS + ('message', ), 'Unknown action: %s' % action

        # Common substitutions for filenames
        tpl_subst = {
            'action': action,
            'newsletter': self.slug
        }

        # Common root path for all the templates
        tpl_root = 'newsletter/message/'

        subject_template = select_template([
            tpl_root + '%(newsletter)s/%(action)s_subject.txt' % tpl_subst,
            tpl_root + '%(action)s_subject.txt' % tpl_subst,
        ])

        text_template = select_template([
            tpl_root + '%(newsletter)s/%(action)s.txt' % tpl_subst,
            tpl_root + '%(action)s.txt' % tpl_subst,
        ])

        if self.send_html:
            html_template = select_template([
                tpl_root + '%(newsletter)s/%(action)s.html' % tpl_subst,
                tpl_root + '%(action)s.html' % tpl_subst,
            ])
        else:
            # HTML templates are not required
            html_template = None

        return (subject_template, text_template, html_template)

    def __unicode__(self):
        return self.title

    class Meta:
        verbose_name = 'newsletter'
        verbose_name_plural = 'newsletters'

    @permalink
    def get_absolute_url(self):
        return (
            'newsletter_detail', (),
            {'newsletter_slug': self.slug}
        )

    @permalink
    def subscribe_url(self):
        return (
            'newsletter_subscribe_request', (),
            {'newsletter_slug': self.slug}
        )

    @permalink
    def unsubscribe_url(self):
        return (
            'newsletter_unsubscribe_request', (),
            {'newsletter_slug': self.slug}
        )

    @permalink
    def update_url(self):
        return (
            'newsletter_update_request', (),
            {'newsletter_slug': self.slug}
        )

    @permalink
    def archive_url(self):
        return (
            'newsletter_archive', (),
            {'newsletter_slug': self.slug}
        )

    def get_sender(self):
        return u'%s <%s>' % (self.sender, self.email)

    def get_subscriptions(self):
        logger.debug(u'Looking up subscribers for %s', self)

        return Subscription.objects.filter(newsletter=self, subscribed=True)

    @classmethod
    def get_default_id(cls):
        try:
            objs = cls.objects.all()
            if objs.count() == 1:
                return objs[0].id
        except:
            pass
        return None


class Subscription(models.Model):
    user = models.ForeignKey(
        User, blank=True, null=True, verbose_name='user'
    )

    name_field = models.CharField(
        db_column='name', max_length=30, blank=True, null=True,
        verbose_name='name', help_text='optional'
    )

    def get_name(self):
        if self.user:
            return self.user.get_full_name()
        return self.name_field

    def set_name(self, name):
        if not self.user:
            self.name_field = name
    name = property(get_name, set_name)

    email_field = models.EmailField(
        db_column='email', verbose_name='e-mail', db_index=True,
        blank=True, null=True
    )

    def get_email(self):
        if self.user:
            return self.user.email
        return self.email_field

    def set_email(self, email):
        if not self.user:
            self.email_field = email
    email = property(get_email, set_email)

    def update(self, action):
        """
        Update subscription according to requested action:
        subscribe/unsubscribe/update/, then save the changes.
        """

        assert action in ('subscribe', 'update', 'unsubscribe')

        # If a new subscription or update, make sure it is subscribed
        # Else, unsubscribe
        if action == 'subscribe' or action == 'update':
            self.subscribed = True
        else:
            self.unsubscribed = True

        logger.debug(
            u'Updated subscription %(subscription)s to %(action)s.',
            {
                'subscription': self,
                'action': action
            }
        )

        # This triggers the subscribe() and/or unsubscribe() methods, taking
        # care of stuff like maintaining the (un)subscribe date.
        self.save()

    def _subscribe(self):
        """
        Internal helper method for managing subscription state
        during subscription.
        """
        logger.debug(u'Subscribing subscription %s.', self)

        self.subscribe_date = now()
        self.subscribed = True
        self.unsubscribed = False

    def _unsubscribe(self):
        """
        Internal helper method for managing subscription state
        during unsubscription.
        """
        logger.debug(u'Unsubscribing subscription %s.', self)

        self.subscribed = False
        self.unsubscribed = True
        self.unsubscribe_date = now()

    def save(self, *args, **kwargs):
        """
        Perform some basic validation and state maintenance of Subscription.

        TODO: Move this code to a more suitable place (i.e. `clean()`) and
        cleanup the code. Refer to comment below and
        https://docs.djangoproject.com/en/dev/ref/models/instances/#django.db.models.Model.clean
        """
        assert self.user or self.email_field, \
            'Neither an email nor a username is set. This asks for inconsistency!'
        assert ((self.user and not self.email_field) or
                (self.email_field and not self.user)), \
            'If user is set, email must be null and vice versa.'

        # This is a lame way to find out if we have changed but using Django
        # API internals is bad practice. This is necessary to discriminate
        # from a state where we have never been subscribed but is mostly for
        # backward compatibility. It might be very useful to make this just
        # one attribute 'subscribe' later. In this case unsubscribed can be
        # replaced by a method property.

        if self.pk:
            assert(Subscription.objects.filter(pk=self.pk).count() == 1)

            subscription = Subscription.objects.get(pk=self.pk)
            old_subscribed = subscription.subscribed
            old_unsubscribed = subscription.unsubscribed

            # If we are subscribed now and we used not to be so, subscribe.
            # If we user to be unsubscribed but are not so anymore, subscribe.
            if ((self.subscribed and not old_subscribed) or
               (old_unsubscribed and not self.unsubscribed)):
                self._subscribe()

                assert not self.unsubscribed
                assert self.subscribed

            # If we are unsubcribed now and we used not to be so, unsubscribe.
            # If we used to be subscribed but are not subscribed anymore,
            # unsubscribe.
            elif ((self.unsubscribed and not old_unsubscribed) or
                  (old_subscribed and not self.subscribed)):
                self._unsubscribe()

                assert not self.subscribed
                assert self.unsubscribed
        else:
            if self.subscribed:
                self._subscribe()
            elif self.unsubscribed:
                self._unsubscribe()

        super(Subscription, self).save(*args, **kwargs)

    ip = models.IPAddressField("IP address", blank=True, null=True)

    newsletter = models.ForeignKey('Newsletter', verbose_name='newsletter')

    create_date = models.DateTimeField(editable=False, default=now)

    activation_code = models.CharField(
        verbose_name='activation code', max_length=40,
        default=make_activation_code
    )

    subscribed = models.BooleanField(
        default=False, verbose_name='subscribed', db_index=True
    )
    subscribe_date = models.DateTimeField(
        verbose_name="subscribe date", null=True, blank=True
    )

    # This should be a pseudo-field, I reckon.
    unsubscribed = models.BooleanField(
        default=False, verbose_name='unsubscribed', db_index=True
    )
    unsubscribe_date = models.DateTimeField(
        verbose_name="unsubscribe date", null=True, blank=True
    )

    def __unicode__(self):
        if self.name:
            return u"%(name)s <%(email)s> to %(newsletter)s" % {
                'name': self.name,
                'email': self.email,
                'newsletter': self.newsletter
            }

        else:
            return u"%(email)s to %(newsletter)s" % {
                'email': self.email,
                'newsletter': self.newsletter
            }

    class Meta:
        verbose_name = 'subscription'
        verbose_name_plural = 'subscriptions'
        unique_together = ('user', 'email_field', 'newsletter')

    def get_recipient(self):
        if self.name:
            return u'%s <%s>' % (self.name, self.email)

        return u'%s' % (self.email)

    def send_activation_email(self, action):
        assert action in ACTIONS, 'Unknown action: %s' % action

        (subject_template, text_template, html_template) = \
            self.newsletter.get_templates(action)

        variable_dict = {
            'subscription': self,
            'site': Site.objects.get_current(),
            'newsletter': self.newsletter,
            'date': self.subscribe_date,
            'STATIC_URL': settings.STATIC_URL,
            'MEDIA_URL': settings.MEDIA_URL
        }

        unescaped_context = Context(variable_dict, autoescape=False)

        subject = subject_template.render(unescaped_context).strip()
        text = text_template.render(unescaped_context)

        message = EmailMultiAlternatives(
            subject, text,
            from_email=self.newsletter.get_sender(),
            to=[self.email]
        )

        if html_template:
            escaped_context = Context(variable_dict)

            message.attach_alternative(
                html_template.render(escaped_context), "text/html"
            )

        message.send()

        logger.debug(
            u'Activation email sent for action "%(action)s" to %(subscriber)s '
            u'with activation code "%(action_code)s".', {
                'action_code': self.activation_code,
                'action': action,
                'subscriber': self
            }
        )

    @permalink
    def subscribe_activate_url(self):
        return ('newsletter_update_activate', (), {
            'newsletter_slug': self.newsletter.slug,
            'email': self.email,
            'action': 'subscribe',
            'activation_code': self.activation_code
        })

    @permalink
    def unsubscribe_activate_url(self):
        return ('newsletter_update_activate', (), {
            'newsletter_slug': self.newsletter.slug,
            'email': self.email,
            'action': 'unsubscribe',
            'activation_code': self.activation_code
        })

    @permalink
    def update_activate_url(self):
        return ('newsletter_update_activate', (), {
            'newsletter_slug': self.newsletter.slug,
            'email': self.email,
            'action': 'update',
            'activation_code': self.activation_code
        })
