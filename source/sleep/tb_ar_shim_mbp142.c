// SPDX-License-Identifier: GPL-2.0
/*
 * tb_ar_shim: suspend/resume fix for the Thunderbolt 3 controller (Intel
 * Alpine Ridge, DSL6540/JHL6540) on Apple MacBookPro14,x.
 *
 * [FOR-UPSTREAM] Out-of-tree carry of two fixes headed for
 * drivers/pci/quirks.c (see upstream/ in https://github.com/orospakr/linux-apple-alpine-ridge-suspend and
 * https://github.com/omacom/omarchy/issues/10593). Installed as a
 * dev_pm_domain on the controller's upstream bridge because that is the only
 * out-of-tree way to run at the right phases; in-tree these are two fixups.
 *
 * Bug 1 (deep/S3): device suspend_noirq runs children first, so the
 * Thunderbolt NHI's tb_lc_set_sleep() drops the whole controller off the bus
 * before the PCI core saves the bridges' config space — it saves all-ones
 * and restores garbage on wake (75-107 s resume, dead NHI, xHCI removed).
 * Fix: save the bridge's and its subtree's config space in suspend_late,
 * before any suspend_noirq callback runs. pci_pm_suspend_noirq() honours
 * state_saved and skips its own save.
 *
 * Bug 2 (s2idle): pci_pm_resume_noirq() skips config restore entirely when
 * skip_bus_pm && pm_suspend_no_platform() (true on this firmware), assuming
 * devices kept their config space — but tb_lc_set_sleep() really cleared it.
 * The NHI then latches going_away (-ESHUTDOWN until reload) and pciehp
 * hot-removes the xHCI. Fix: restore the saved state ourselves in
 * resume_noirq, parents before children. pci_restore_state() consumes
 * state_saved, so under S3 (where the core does restore) this is a no-op.
 *
 * Upstream base reports validation on MacBookPro14,1. This model-specific
 * draft adapts registration to BOTH onboard controller trees on MacBookPro14,2.
 * It is compile-reviewed only: NO hardware validation is claimed.
 * Base: orospakr/linux-apple-alpine-ridge-suspend
 * commit 155ffe3a4a963bc8d84df72fa53f14eb16ea9a60.
 * The original config save/restore mechanism is retained for review.
 */
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/acpi.h>
#include <linux/pm_domain.h>
#include <linux/delay.h>
#include <linux/ktime.h>
#include <linux/list.h>
#include <linux/slab.h>
#include <linux/dmi.h>

/* resume_noirq: max wait for the upstream bridge to answer config reads.
 * Measured: immediate on s2idle (rails never drop), <1 s on S3 (platform
 * re-powers the chip before the first noirq callback). */
#define BRIDGE_WAIT_MS	3000
/* resume_noirq: shared budget for the subtree restore walk. Measured need is
 * ~1 ms; the budget has never been consumed in validation. */
#define SUBTREE_WAIT_MS	200

struct tb_ar_bridge {
	struct list_head node;
	struct pci_dev *pdev;
	const struct dev_pm_ops *bus_pm;
	struct dev_pm_domain pm_domain;
	bool installed;
};

static LIST_HEAD(bridge_contexts);

static int save_cb(struct pci_dev *dev, void *data)
{
	int *n = data;
	u32 id;

	pci_read_config_dword(dev, PCI_VENDOR_ID, &id);
	if (id == 0xffffffff) {
		pci_warn(dev, "tb_ar_shim: not readable at suspend_late, not saving\n");
		return 0;
	}
	if (dev->class == PCI_CLASS_SERIAL_USB_XHCI) {
		/*
		 * The controller's xHCI is usually runtime-suspended (D3hot,
		 * state already saved) by now — leave it to the core. If it
		 * is still in D0, save it and let it reach D3hot with wake
		 * armed while its config space is still readable.
		 */
		if (dev->current_state != PCI_D0)
			return 0;
		pci_save_state(dev);
		(*n)++;
		pci_prepare_to_sleep(dev);
		return 0;
	}
	pci_save_state(dev);
	(*n)++;
	return 0;
}

static int shim_suspend_late(struct device *dev)
{
	struct pci_dev *pdev = to_pci_dev(dev);
	struct tb_ar_bridge *ctx = container_of(dev->pm_domain,
					      struct tb_ar_bridge, pm_domain);
	int ret, n = 0;

	ret = ctx->bus_pm->suspend_late ? ctx->bus_pm->suspend_late(dev) : 0;
	if (ret)
		return ret;
	save_cb(pdev, &n);
	if (pdev->subordinate)
		pci_walk_bus(pdev->subordinate, save_cb, &n);
	pci_info(pdev, "tb_ar_shim: suspend_late: saved config of %d devices\n", n);
	return 0;
}

/*
 * Poll one subtree device until it answers config reads, spending from a
 * shared time budget, then restore its saved config. pci_walk_bus is
 * pre-order and the caller restored the bridge itself first, so each
 * device's path is programmed before we reach it.
 */
static int restore_cb(struct pci_dev *dev, void *data)
{
	int *budget = data;
	u32 id = 0xffffffff;

	for (;;) {
		pci_read_config_dword(dev, PCI_VENDOR_ID, &id);
		if (id != 0xffffffff && id != 0)
			break;
		if (*budget <= 0) {
			pci_warn(dev, "tb_ar_shim: not readable at resume_noirq, budget spent\n");
			return 0;
		}
		msleep(10);
		*budget -= 10;
	}
	if (dev->state_saved)
		pci_restore_state(dev);
	return 0;
}

static int shim_resume_noirq(struct device *dev)
{
	struct pci_dev *pdev = to_pci_dev(dev);
	struct tb_ar_bridge *ctx = container_of(dev->pm_domain,
					      struct tb_ar_bridge, pm_domain);
	ktime_t t0 = ktime_get();
	u32 id = 0xffffffff;
	int budget = SUBTREE_WAIT_MS;
	int waited = 0;
	int ret;

	while (waited <= BRIDGE_WAIT_MS) {
		pci_read_config_dword(pdev, PCI_VENDOR_ID, &id);
		if (id != 0xffffffff && id != 0)
			break;
		msleep(10);
		waited += 10;
	}
	if (id == 0xffffffff || id == 0)
		pci_err(pdev, "tb_ar_shim: bridge not readable %d ms after wake\n",
			BRIDGE_WAIT_MS);
	ret = ctx->bus_pm->resume_noirq ? ctx->bus_pm->resume_noirq(dev) : 0;
	if (ret)
		return ret;
	if (pdev->state_saved)
		pci_restore_state(pdev);
	if (pdev->subordinate)
		pci_walk_bus(pdev->subordinate, restore_cb, &budget);
	pci_info(pdev, "tb_ar_shim: resume_noirq done in %lld us (subtree budget left %d ms)\n",
		 ktime_us_delta(ktime_get(), t0), budget);
	return ret;
}

/* Restore only domains this draft installed; discovery itself changes nothing. */
static void release_contexts(void)
{
	struct tb_ar_bridge *ctx, *tmp;

	list_for_each_entry_safe_reverse(ctx, tmp, &bridge_contexts, node) {
		if (ctx->installed) {
			device_release_driver(&ctx->pdev->dev);
			dev_pm_domain_set(&ctx->pdev->dev, NULL);
			if (device_attach(&ctx->pdev->dev) <= 0)
				pci_warn(ctx->pdev, "tb_ar_shim_mbp142: driver re-attach failed\n");
		}
		list_del(&ctx->node);
		pci_dev_put(ctx->pdev);
		kfree(ctx);
	}
}

static int __init shim_init(void)
{
	struct pci_dev *pdev = NULL;
	struct tb_ar_bridge *ctx;
	acpi_handle bridge, sxfp;
	unsigned int count = 0;
	int ret = -ENODEV;

	/* No claim is made for any other model by this experimental draft. */
	if (!dmi_match(DMI_PRODUCT_NAME, "MacBookPro14,2"))
		return -ENODEV;

	/* Discover and validate BOTH onboard branches before changing either. */
	while ((pdev = pci_get_device(PCI_VENDOR_ID_INTEL, 0x1578, pdev))) {
		bridge = ACPI_HANDLE(&pdev->dev);
		if (!pci_is_bridge(pdev) || !bridge ||
		    ACPI_FAILURE(acpi_get_handle(bridge, "DSB0.NHI0.SXFP", &sxfp)))
			continue;
		if (pdev->dev.pm_domain || !pdev->dev.bus ||
		    !pdev->dev.bus->pm || !pdev->dev.driver ||
		    strcmp(pdev->dev.driver->name, "pcieport")) {
			pci_err(pdev, "tb_ar_shim_mbp142: existing PM domain or driver needs review\n");
			ret = -EBUSY;
			goto put_iterator;
		}
		ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
		if (!ctx) {
			ret = -ENOMEM;
			goto put_iterator;
		}
		ctx->pdev = pci_dev_get(pdev);
		ctx->bus_pm = pdev->dev.bus->pm;
		ctx->pm_domain.ops = *ctx->bus_pm;
		ctx->pm_domain.ops.suspend_late = shim_suspend_late;
		ctx->pm_domain.ops.resume_noirq = shim_resume_noirq;
		list_add_tail(&ctx->node, &bridge_contexts);
		count++;
	}
	if (count != 2) {
		pr_err("tb_ar_shim_mbp142: expected two Apple bridges, found %u; no PM domains changed\n", count);
		goto fail;
	}

	list_for_each_entry(ctx, &bridge_contexts, node) {
		device_release_driver(&ctx->pdev->dev);
		dev_pm_domain_set(&ctx->pdev->dev, &ctx->pm_domain);
		ctx->installed = true;
		ret = device_attach(&ctx->pdev->dev);
		if (ret <= 0) {
			ret = ret < 0 ? ret : -ENODEV;
			pci_err(ctx->pdev, "tb_ar_shim_mbp142: attach failed; rolling back\n");
			goto fail;
		}
		pci_info(ctx->pdev, "tb_ar_shim_mbp142: experimental PM domain installed\n");
	}
	pr_info("tb_ar_shim_mbp142: guarded both onboard controller trees\n");
	return 0;

put_iterator:
	pci_dev_put(pdev);
fail:
	release_contexts();
	return ret;
}

static void __exit shim_exit(void)
{
	release_contexts();
}

module_init(shim_init);
module_exit(shim_exit);
/* Manual-load review build: no autoload alias or installation hook. */
MODULE_LICENSE("GPL");
MODULE_VERSION("1.0.0-mbp142-review1");
MODULE_DESCRIPTION("UNVALIDATED dual-controller PM draft for MacBookPro14,2");
