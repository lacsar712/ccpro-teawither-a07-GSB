from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import OuterRef, Subquery


class Garden(models.Model):
    name = models.CharField("茶园名称", max_length=120)
    altitudeBand = models.CharField("海拔带", max_length=60)
    notes = models.TextField("备注", blank=True, default="")

    class Meta:
        ordering = ["name"]
        verbose_name = "茶园"
        verbose_name_plural = "茶园"

    def __str__(self):
        return self.name

    def latest_gear_log(self):
        return self.fan_gear_logs.order_by("-switchedAt", "-id").first()

    def gear_qualified(self):
        """园级达标：最近一次风机档位切换志的档位达到约定档位（含）。"""
        log = self.latest_gear_log()
        return log is not None and log.gear >= FanGearLog.GEAR_THRESHOLD

    def gear_covers_batch(self, started_at):
        """批次门槛：最近一次切换达到约定档位，且切换时刻不早于批次开始。"""
        log = self.latest_gear_log()
        return (
            log is not None
            and log.gear >= FanGearLog.GEAR_THRESHOLD
            and log.switchedAt >= started_at
        )


class Trough(models.Model):
    STATUS_LOADING = "loading"
    STATUS_WITHERING = "withering"
    STATUS_READY = "ready"
    STATUS_CHOICES = [
        (STATUS_LOADING, "装叶中"),
        (STATUS_WITHERING, "萎凋中"),
        (STATUS_READY, "可下槽"),
    ]

    garden = models.ForeignKey(
        Garden,
        on_delete=models.CASCADE,
        related_name="troughs",
        verbose_name="茶园",
    )
    troughCode = models.CharField("槽位编号", max_length=40)
    cultivar = models.CharField("茶树品种", max_length=80)
    loadKg = models.DecimalField("装叶量(kg)", max_digits=10, decimal_places=2)
    status = models.CharField(
        "状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_LOADING,
    )

    class Meta:
        ordering = ["garden__name", "troughCode"]
        verbose_name = "萎凋槽"
        verbose_name_plural = "萎凋槽"
        constraints = [
            models.UniqueConstraint(
                fields=["garden", "troughCode"],
                name="uniq_trough_code_per_garden",
            ),
        ]

    def __str__(self):
        return f"{self.garden.name}-{self.troughCode}"

    def latest_batch(self):
        return self.batches.order_by("-startedAt", "-id").first()

    def clean(self):
        super().clean()
        if self.status != self.STATUS_READY:
            return
        latest = None
        if self.pk:
            latest = (
                WitherBatch.objects.filter(trough_id=self.pk)
                .order_by("-startedAt", "-id")
                .first()
            )
        if latest is None or latest.actualMoisture is None or latest.actualMoisture > 40:
            raise ValidationError(
                {
                    "status": "无法设为可下槽：最新萎凋批次的实测含水率为空或高于 40%。"
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class WitherBatch(models.Model):
    trough = models.ForeignKey(
        Trough,
        on_delete=models.CASCADE,
        related_name="batches",
        verbose_name="萎凋槽",
    )
    startedAt = models.DateTimeField("开始时间")
    targetMoisture = models.DecimalField(
        "目标含水率(%)", max_digits=5, decimal_places=2
    )
    actualMoisture = models.DecimalField(
        "实测含水率(%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    rollGrade = models.CharField("揉捻等级", max_length=40)

    class Meta:
        ordering = ["-startedAt", "-id"]
        verbose_name = "萎凋批次"
        verbose_name_plural = "萎凋批次"

    def __str__(self):
        return f"{self.trough} @ {self.startedAt:%Y-%m-%d %H:%M}"


class FanGearLog(models.Model):
    """风机档位切换志：同一茶园切换时刻精确到分钟不得重复。"""

    GEAR_MIN = 1
    GEAR_MAX = 5
    GEAR_THRESHOLD = 3
    GEAR_CHOICES = [(i, f"{i} 档") for i in range(GEAR_MIN, GEAR_MAX + 1)]

    garden = models.ForeignKey(
        Garden,
        on_delete=models.CASCADE,
        related_name="fan_gear_logs",
        verbose_name="所属茶园",
    )
    switchedAt = models.DateTimeField("切换时刻")
    gear = models.PositiveSmallIntegerField(
        "档位",
        choices=GEAR_CHOICES,
        validators=[
            MinValueValidator(GEAR_MIN),
            MaxValueValidator(GEAR_MAX),
        ],
    )
    operator = models.CharField("操作人", max_length=80)
    notes = models.TextField("备注", blank=True, default="")

    class Meta:
        ordering = ["-switchedAt", "-id"]
        verbose_name = "风机档位切换志"
        verbose_name_plural = "风机档位切换志"
        constraints = [
            models.UniqueConstraint(
                fields=["garden", "switchedAt"],
                name="uniq_fangeolog_minute_per_garden",
            ),
        ]

    def __str__(self):
        return f"{self.garden.name} 风机 {self.gear} 档 @ {self.switchedAt:%Y-%m-%d %H:%M}"

    def clean(self):
        super().clean()
        # 切换时刻精确到分钟：秒以下归零，配合唯一约束保证同园同分钟不重复
        if self.switchedAt:
            self.switchedAt = self.switchedAt.replace(second=0, microsecond=0)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


def latest_gear_subquery():
    """每园最近一条切换志的档位（按切换时刻、id 排序），可用于 annotate。"""
    return Subquery(
        FanGearLog.objects.filter(garden=OuterRef("pk"))
        .order_by("-switchedAt", "-id")
        .values("gear")[:1]
    )
