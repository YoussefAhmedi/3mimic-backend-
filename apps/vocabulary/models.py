from django.db import models


class DictionaryEntry(models.Model):
    """
    A cached dictionary lookup: how `word` (in `language`) is explained to a speaker of `native_language`.
    Rows come from the configured dictionary provider the first time a word is tapped, or from an admin.
    """
    language = models.ForeignKey("levels.Language", on_delete=models.CASCADE, related_name="+")
    native_language = models.ForeignKey("levels.Language", on_delete=models.CASCADE, related_name="+")
    lookup_key = models.CharField(max_length=100, help_text="Lower-cased form the learner tapped")
    headword = models.CharField(max_length=100, help_text="Dictionary form, e.g. 'estar' for 'estaba'")
    part_of_speech = models.CharField(max_length=60, blank=True)
    pronunciation = models.CharField(max_length=100, blank=True)
    meaning = models.CharField(max_length=300)
    example = models.CharField(max_length=300, blank=True)
    example_translation = models.CharField(max_length=300, blank=True)
    source = models.CharField(max_length=30, default="admin")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "dictionary entries"
        constraints = [models.UniqueConstraint(fields=["language", "native_language", "lookup_key"],
                                                name="uniq_dictionary_lookup")]

    def __str__(self):
        return f"{self.lookup_key} ({self.language.code}→{self.native_language.code})"


class SavedWord(models.Model):
    """'Words' tab: a dictionary entry the user added to favourites."""
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="saved_words")
    entry = models.ForeignKey(DictionaryEntry, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "entry"], name="uniq_saved_word")]


class FavoriteSnippet(models.Model):
    """'Favorites' tab: a snippet the user hearted."""
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="favorite_snippets")
    snippet = models.ForeignKey("snippets.Snippet", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "snippet"], name="uniq_favorite_snippet")]


class CachedTranslation(models.Model):
    """
    A sentence already translated once (caption lines, listening hints). Kept in the database so that a
    restart, a rate limit or a blocked IP never makes the app translate the same sentence twice.
    """
    language = models.CharField(max_length=10)  # language of `text`
    native = models.CharField(max_length=10)    # language of `translation`
    text_hash = models.CharField(max_length=40)
    text = models.TextField()
    translation = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["language", "native", "text_hash"],
                                                name="uniq_cached_translation")]
        indexes = [models.Index(fields=["language", "native"])]

    def __str__(self):
        return f"{self.language}→{self.native}: {self.text[:40]}"
