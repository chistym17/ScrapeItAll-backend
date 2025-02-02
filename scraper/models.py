from django.db import models


class ScrapedData(models.Model):
    url = models.URLField()
    content = models.TextField()
    scraped_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.url} - {self.scraped_at}"
