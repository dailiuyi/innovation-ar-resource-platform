<template>
  <svg :class="svgClass" aria-hidden="true">
    <use :xlink:href="iconName" :fill="color" />
  </svg>
</template>

<script>
export default defineComponent({
  props: {
    iconClass: {
      type: String,
      required: true
    },
    className: {
      type: String,
      default: ''
    },
    color: {
      type: String,
      default: ''
    },
  },
  setup(props) {
    return {
      iconName: computed(() => `#icon-${props.iconClass}`),
      svgClass: computed(() => {
        const line = props.iconClass.startsWith('nav-') ? ' svg-icon-line' : ''
        return props.className ? `svg-icon ${props.className}${line}` : `svg-icon${line}`
      })
    }
  }
})
</script>

<style scope lang="scss">
.sub-el-icon,
.nav-icon {
  display: inline-block;
  font-size: 15px;
  margin-right: 12px;
  position: relative;
}

.svg-icon {
  width: 1em;
  height: 1em;
  position: relative;
  fill: currentColor;
  vertical-align: -2px;
}

/* nav-* 是线性图标：靠描边绘制，不能被上面的 fill 填实。 */
.svg-icon.svg-icon-line {
  fill: none;
  width: 1.15em;
  height: 1.15em;
  vertical-align: -0.2em;
}
</style>
