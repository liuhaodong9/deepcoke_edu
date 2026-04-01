import Vue from 'vue'
import { Dropdown, DropdownItem, DropdownMenu, Button, Form, FormItem, Input, Message, Container, Header, Aside, Main, Menu, Submenu, MenuItemGroup, MenuItem, Breadcrumb, BreadcrumbItem, Card, Row, Col, Table, TableColumn, Select, Option, MessageBox, Dialog, Pagination, Tabs, Upload, Tooltip } from 'element-ui'

// Vue.use注册为全局组件
Vue.use(Button)
Vue.use(Form)
Vue.use(FormItem)
Vue.use(Input)
Vue.use(Container)
Vue.use(Header)
Vue.use(Aside)
Vue.use(Main)
Vue.use(Menu)
Vue.use(Submenu)
Vue.use(MenuItemGroup)
Vue.use(MenuItem)
Vue.use(Breadcrumb)
Vue.use(BreadcrumbItem)
Vue.use(Card)
Vue.use(Row)
Vue.use(Col)
Vue.use(Table)
Vue.use(TableColumn)
Vue.use(Select)
Vue.use(Option)
Vue.use(Dialog)
Vue.use(Pagination)
Vue.use(Tabs)
Vue.use(Upload)
Vue.use(Tooltip)
Vue.use(Dropdown)
Vue.use(DropdownItem)
Vue.use(DropdownMenu)

Vue.prototype.$message = Message // message需要全局挂载,$message任意名字，可自己命名，后面Message固定，用this.$message调用
Vue.prototype.$confirm = MessageBox.confirm // MessageBox需要全局挂载,不用use
