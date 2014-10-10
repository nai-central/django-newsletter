import logging
logger = logging.getLogger(__name__)

from django.conf import settings
from django.conf.urls import patterns, url

from django.contrib import admin, messages

from django.http import HttpResponseRedirect

from django.template import RequestContext

from django.shortcuts import render_to_response

from django.utils.translation import ugettext, ungettext, ugettext_lazy as _
from django.utils.formats import date_format

from .models import Newsletter, Subscription

from .admin_forms import ImportForm, ConfirmForm, SubscriptionAdminForm
from .admin_utils import ExtendibleModelAdminMixin

# Contsruct URL's for icons
ICON_URLS = {
    'yes': '%sadmin/img/icon-yes.gif' % settings.STATIC_URL,
    'wait': '%snewsletter/admin/img/waiting.gif' % settings.STATIC_URL,
    'submit': '%snewsletter/admin/img/submitting.gif' % settings.STATIC_URL,
    'no': '%sadmin/img/icon-no.gif' % settings.STATIC_URL
}


class NewsletterAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'admin_subscriptions', 'admin_messages', 'admin_submissions'
    )
    prepopulated_fields = {'slug': ('title',)}

    """ List extensions """
    def admin_messages(self, obj):
        return '<a href="../message/?newsletter__id__exact=%s">%s</a>' % (
            obj.id, ugettext('Messages')
        )
    admin_messages.allow_tags = True
    admin_messages.short_description = ''

    def admin_subscriptions(self, obj):
        return \
            '<a href="../subscription/?newsletter__id__exact=%s">%s</a>' % \
            (obj.id, ugettext('Subscriptions'))
    admin_subscriptions.allow_tags = True
    admin_subscriptions.short_description = ''

    def admin_submissions(self, obj):
        return '<a href="../submission/?newsletter__id__exact=%s">%s</a>' % (
            obj.id, ugettext('Submissions')
        )
    admin_submissions.allow_tags = True
    admin_submissions.short_description = ''


class SubscriptionAdmin(admin.ModelAdmin, ExtendibleModelAdminMixin):
    form = SubscriptionAdminForm
    list_display = (
        'name', 'email', 'admin_newsletter', 'admin_subscribe_date',
        'admin_unsubscribe_date', 'admin_status_text', 'admin_status'
    )
    list_display_links = ('name', 'email')
    list_filter = (
        'newsletter', 'subscribed', 'unsubscribed', 'subscribe_date'
    )
    search_fields = (
        'name_field', 'email_field', 'user__first_name', 'user__last_name',
        'user__email'
    )
    readonly_fields = (
        'ip', 'subscribe_date', 'unsubscribe_date', 'activation_code'
    )
    date_hierarchy = 'subscribe_date'
    actions = ['make_subscribed', 'make_unsubscribed']

    """ List extensions """
    def admin_newsletter(self, obj):
        return '<a href="../newsletter/%s/">%s</a>' % (
            obj.newsletter.id, obj.newsletter
        )
    admin_newsletter.short_description = ugettext('newsletter')
    admin_newsletter.allow_tags = True

    def admin_status(self, obj):
        if obj.unsubscribed:
            return u'<img src="%s" width="10" height="10" alt="%s"/>' % (
                ICON_URLS['no'], self.admin_status_text(obj))

        if obj.subscribed:
            return u'<img src="%s" width="10" height="10" alt="%s"/>' % (
                ICON_URLS['yes'], self.admin_status_text(obj))
        else:
            return u'<img src="%s" width="10" height="10" alt="%s"/>' % (
                ICON_URLS['wait'], self.admin_status_text(obj))

    admin_status.short_description = ''
    admin_status.allow_tags = True

    def admin_status_text(self, obj):
        if obj.subscribed:
            return ugettext("Subscribed")
        elif obj.unsubscribed:
            return ugettext("Unsubscribed")
        else:
            return ugettext("Unactivated")
    admin_status_text.short_description = ugettext('Status')

    def admin_subscribe_date(self, obj):
        if obj.subscribe_date:
            return date_format(obj.subscribe_date)
        else:
            return ''
    admin_subscribe_date.short_description = _("subscribe date")

    def admin_unsubscribe_date(self, obj):
        if obj.unsubscribe_date:
            return date_format(obj.unsubscribe_date)
        else:
            return ''
    admin_unsubscribe_date.short_description = _("unsubscribe date")

    """ Actions """
    def make_subscribed(self, request, queryset):
        rows_updated = queryset.update(subscribed=True)
        self.message_user(
            request,
            ungettext(
                "%s user has been successfully subscribed.",
                "%s users have been successfully subscribed.",
                rows_updated
            ) % rows_updated
        )
    make_subscribed.short_description = _("Subscribe selected users")

    def make_unsubscribed(self, request, queryset):
        rows_updated = queryset.update(subscribed=False)
        self.message_user(
            request,
            ungettext(
                "%s user has been successfully unsubscribed.",
                "%s users have been successfully unsubscribed.",
                rows_updated
            ) % rows_updated
        )
    make_unsubscribed.short_description = _("Unsubscribe selected users")

    """ Views """
    def subscribers_import(self, request):
        if request.POST:
            form = ImportForm(request.POST, request.FILES)
            if form.is_valid():
                request.session['addresses'] = form.get_addresses()
                return HttpResponseRedirect('confirm/')
        else:
            form = ImportForm()

        return render_to_response(
            "admin/newsletter/subscription/importform.html",
            {'form': form},
            RequestContext(request, {}),
        )

    def subscribers_import_confirm(self, request):
        # If no addresses are in the session, start all over.
        if not 'addresses' in request.session:
            return HttpResponseRedirect('../')

        addresses = request.session['addresses']
        logger.debug('Confirming addresses: %s', addresses)
        if request.POST:
            form = ConfirmForm(request.POST)
            if form.is_valid():
                try:
                    for address in addresses.values():
                        address.save()
                finally:
                    del request.session['addresses']

                messages.success(
                    request,
                    _('%s subscriptions have been successfully added.') %
                    len(addresses)
                )

                return HttpResponseRedirect('../../')
        else:
            form = ConfirmForm()

        return render_to_response(
            "admin/newsletter/subscription/confirmimportform.html",
            {'form': form, 'subscribers': addresses},
            RequestContext(request, {}),
        )

    """ URLs """
    def get_urls(self):
        urls = super(SubscriptionAdmin, self).get_urls()

        my_urls = patterns(
            '',
            url(r'^import/$',
                self._wrap(self.subscribers_import),
                name=self._view_name('import')),
            url(r'^import/confirm/$',
                self._wrap(self.subscribers_import_confirm),
                name=self._view_name('import_confirm')),

            # Translated JS strings - these should be app-wide but are
            # only used in this part of the admin. For now, leave them here.
            url(r'^jsi18n/$',
                'django.views.i18n.javascript_catalog',
                {'packages': ('newsletter',)},
                name='newsletter_js18n')
        )

        return my_urls + urls


admin.site.register(Newsletter, NewsletterAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
