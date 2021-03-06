import logging

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, BooleanField, Avg
from django.db.models import Prefetch
from django.db.models import When
from django.forms import ModelForm
from django.http import HttpResponseForbidden, HttpResponseRedirect, Http404, HttpResponse, JsonResponse
from django.shortcuts import resolve_url, get_list_or_404, render
from django.template import RequestContext
from django.views.decorators.http import require_POST
from django.views.generic.list import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, UpdateView, FormMixin, ModelFormMixin
from .models import Post, Comment, Like
from django.db.models import Count
from django.contrib.auth.decorators import login_required
from .forms import *
from django.template.loader import render_to_string
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)

# Create your views here.
@login_required
@require_POST
def catch_like_view(request):
    try:
        print(request.POST)
        if request.POST['contenttype'] == u'post':
            post = Post.objects.get(id=int(request.POST['id']))
            if not post.likes.all().filter(author=request.user).exists():
                like = Like(content_object=post, author=request.user)
                like.save()
        elif request.POST['contenttype'] == u'comment':
            comment = Comment.objects.get(id=int(request.POST['id']))
            if not comment.likes.all().filter(author=request.user).exists():
                like = Like(content_object=comment, author=request.user)
                like.save()
    except Post.DoesNotExist:
        raise Http404("You are trying to like non-existing post")
    return HttpResponse("Great!")


def get_likes(request, pk):
    lc = Like.objects.filter(content_type=ContentType.objects.get(model="post"), object_id=pk).count()
    comments = [i for i in Post.objects.get(id=pk).comment_set.annotate(lc=Count('likes'))]
    commdict = dict()
    for comment in comments:
        commdict[comment.id] = comment.lc
    return JsonResponse({'postlike': lc, 'commentlikes': commdict})


def get_comms(request, pk):
    post = Post.objects.get(id=pk)
    comments = []
    idcomm = request.GET['id']
    # aware_utc_dt = utc_dt.replace(tzinfo=pytz.utc)
    # tz = pytz.timezone('Europe/Moscow')
    # dt = aware_utc_dt.astimezone(tz)
    if request.GET['id']:
        comments = [i for i in Post.objects.get(id=pk).comment_set.filter \
            (post__comment__id__gt=idcomm).annotate(lc=Count('likes'))]
    commdict = dict()
    for comment in comments:
        boo = not request.user.is_anonymous and comment.likes.all().filter(
            author=request.user).exists()
        commdict[comment.id] = render_to_string("comment.html",
                                                {'post': post, 'comment': comment, 'lc': comment.lc, 'liked': boo,
                                                 'user': request.user}, request=request)
    return JsonResponse({"commenttext": commdict})


class PostList(ListView):
    template_name = "post_list.html"
    model = Post
    context_object_name = 'posts'
    paginate_by = 10

    queryset = Post.objects.annotate(lc=Count('likes')).select_related('author')

    def get_context_data(self, **kwargs):
        cd = super(PostList, self).get_context_data()
        cd['avglikes'] = Post.objects.annotate(lc=Count('likes')).aggregate(avglikes=Avg('lc'))['avglikes']
        return cd

    def get_queryset(self):
        qs = super(PostList, self).get_queryset()
        author = self.request.GET.get("author")
        sort = self.request.GET.get("sort")
        if author:
            qs = get_list_or_404(qs.filter(author__username__contains=author))
        if sort:
            if (sort == 'earlier'):
                qs = get_list_or_404(qs.order_by('-created_at'))
            elif sort == 'later':
                qs = get_list_or_404(qs.order_by('created_at'))
            elif sort == 'liked':
                qs = qs.order_by('-lc')
        return qs


class PostView(FormMixin, DetailView):
    template_name = "post_detailed.html"
    model = Post
    form_class = CommentForm

    def get_context_data(self, **kwargs):
        data = super(PostView, self).get_context_data(**kwargs)
        like_qs = Like.objects.filter(author_id=self.request.user.id)
        data["comments"] = self.object.comment_set.all().prefetch_related(Prefetch('likes', queryset=like_qs)) \
            .annotate(lc=Count('likes')).select_related('author')
        data["form"] = self.get_form(form_class=self.form_class)
        return data

    def get_queryset(self):
        like_qs = Like.objects.filter(author_id=self.request.user.id)
        qs = super(PostView, self).get_queryset()
        qs = qs.annotate(lc=Count('likes')).select_related('author') \
            .prefetch_related(Prefetch('likes', queryset=like_qs))
        return qs

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden()
        form = self.get_form(form_class=self.form_class)
        form.instance.author = self.request.user
        form.instance.post = self.get_object()

        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def form_valid(self, form):
        form.save()
        return super(PostView, self).form_valid(form)

    def get_form(self, form_class=None):
        form = super(PostView, self).get_form(form_class)
        if self.request.user.is_anonymous:
            form = None
        return form

    def get_success_url(self):
        return resolve_url('blogs:blog_post', self.kwargs['pk'])
        # olololo


class LatestList(ListView):
    paginate_by = 10
    template_name = "post_list.html"
    queryset = Post.objects.annotate(lc=Count('likes')).select_related('author').order_by('-created_at')[:10]
    context_object_name = 'posts'


class EditPost(UpdateView):
    def get_success_url(self):
        return resolve_url('blogs:blog_post', pk=self.object.pk)

    def dispatch(self, request, *args, **kwargs):
        handler = super(EditPost, self).dispatch(request, *args, **kwargs)
        if self.object.author != request.user:
            return HttpResponseForbidden(u"U cant touch this.")
        return handler

    def get_context_data(self, **kwargs):
        cd = super(EditPost, self).get_context_data(**kwargs)
        cd['create'] = False
        return cd

    template_name = "edit.html"
    model = Post
    form_class = PostForm


class NewPost(CreateView):
    template_name = "edit.html"
    model = Post
    form_class = PostForm

    def get_success_url(self):
        return resolve_url('blogs:blog_post', self.object.pk)

    def get_form(self, form_class=None):
        form = super(NewPost, self).get_form(form_class)
        form.instance.author = self.request.user
        return form

    def get_context_data(self, **kwargs):
        cd = super(NewPost, self).get_context_data(**kwargs)
        cd['create'] = True
        return cd

    def form_valid(self, form):
        logger.critical("New post created")
        return super(NewPost, self).form_valid(form)


