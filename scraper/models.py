from django.db import models


class ScrapedData(models.Model):
    url = models.URLField()
    content = models.TextField()
    scraped_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50)
    size = models.IntegerField(default=0)
    selected = models.BooleanField(default=True)
    processed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.url} - {self.scraped_at}"


class SitemapURL(models.Model):
    url = models.URLField()
    size = models.IntegerField(default=0)
    selected = models.BooleanField(default=True)
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.url
