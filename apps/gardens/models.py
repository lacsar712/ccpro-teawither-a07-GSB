from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import OuterRef, Subquery

# 萎凋槽风机档位门槛：最近一次切换达到该档位才允许写入批次实测含水率
GEAR_THRESHOLD = 3


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
    """风机档位切换志：记录茶园风机档位何时被切到几档。"""

    GEAR_CHOICES = [(i, f"{i} 档") for i in range(1, 6)]

    garden = models.ForeignKey(
        Garden,
        on_delete=models.CASCADE,
        related_name="gear_logs",
        verbose_name="茶园",
    )
    switchedAt = models.DateTimeField("切换时刻")
    gear = models.PositiveSmallIntegerField("档位", choices=GEAR_CHOICES)
    operator = models.CharField("操作人", max_length=80)
    notes = models.TextField("备注", blank=True, default="")

    class Meta:
        ordering = ["-switchedAt", "-id"]
        verbose_name = "风机档位志"
        verbose_name_plural = "风机档位志"
        constraints = [
            models.UniqueConstraint(
                fields=["garden", "switchedAt"],
                name="uniq_gear_log_minute_per_garden",
            ),
        ]

    def __str__(self):
        return f"{self.garden.name} {self.switchedAt:%Y-%m-%d %H:%M} → {self.gear}档"

    def clean(self):
        super().clean()
        if self.switchedAt:
            # 切换时刻精确到分钟：秒与毫秒一律归零
            self.switchedAt = self.switchedAt.replace(second=0, microsecond=0)
        if self.garden_id and self.switchedAt:
            dup = FanGearLog.objects.filter(
                garden_id=self.garden_id, switchedAt=self.switchedAt
            )
            if self.pk:
                dup = dup.exclude(pk=self.pk)
            if dup.exists():
                raise ValidationError(
                    {
                        "switchedAt": "同一茶园的切换时刻（精确到分钟）不得重复，"
                        "该园在该分钟已有一条风机档位切换志。"
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


def garden_gear_ready(garden, since=None):
    """该园是否存在档位达到门槛（≥3）的切换志。

    传入 since（批次开始时间）时，切换时刻须不早于该时刻（按分钟比较）。
    """
    qs = garden.gear_logs.filter(gear__gte=GEAR_THRESHOLD)
    if since is not None:
        qs = qs.filter(switchedAt__gte=since.replace(second=0, microsecond=0))
    return qs.exists()


def gardens_with_latest_gear():
    """茶园查询集，注解最近档位（latest_gear）与切换时刻（latest_gear_at）。

    首页「档位已达标园」统计与茶园列表「已达标」筛选共用此查询，
    保证两处数字一致。
    """
    latest = FanGearLog.objects.filter(garden=OuterRef("pk")).order_by(
        "-switchedAt", "-id"
    )
    return Garden.objects.annotate(
        latest_gear=Subquery(latest.values("gear")[:1]),
        latest_gear_at=Subquery(latest.values("switchedAt")[:1]),
    )
