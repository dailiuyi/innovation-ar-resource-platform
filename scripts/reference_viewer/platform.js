// Same-origin launcher for the reference viewer: lists published scenes and their real variants from the platform's
// anonymous client API and opens /viewer/<sceneId>?showdemo=4dv&variant=<variantId> with a full page navigation.
(() => {
  const scene = document.getElementById('scene');
  const variant = document.getElementById('variant');
  const open = document.getElementById('open');
  const status = document.getElementById('status');
  let scenes = [];

  const fill = (select, entries) => {
    select.replaceChildren(...entries.map(([value, label]) => Object.assign(document.createElement('option'), { value, textContent: label })));
    select.disabled = entries.length === 0;
  };
  const showVariants = () => {
    const current = scenes.find((item) => item.id === scene.value);
    fill(variant, current ? current.variants.map((v) => [v.id, `${v.name} (${v.id}, ${v.segmentCount} 段, ${v.durationSeconds}s)`]) : []);
    if (current) variant.value = current.defaultVariant;
    open.disabled = !current;
  };

  async function load() {
    const loaded = [];
    for (let offset = 0; ; offset += 100) {
      const response = await fetch(`/api/v1/client/scenes?limit=100&offset=${offset}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const page = await response.json();
      loaded.push(...page.items);
      if (page.items.length === 0 || loaded.length >= page.total) return loaded;
    }
  }

  scene.addEventListener('change', showVariants);
  open.addEventListener('click', () => {
    window.location.assign(`/viewer/${encodeURIComponent(scene.value)}?showdemo=4dv&variant=${encodeURIComponent(variant.value)}`);
  });
  load().then((items) => {
    scenes = items;
    fill(scene, items.map((item) => [item.id, item.name]));
    status.textContent = items.length ? '' : '平台目录为空：没有已发布的场景';
    showVariants();
  }, (error) => { status.textContent = `读取平台目录失败：${error.message}`; });
})();
