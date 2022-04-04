const client = require('contentful').createClient({
  space: '3af6cjtdd6tx',
  accessToken: 'rP4uk19uHaBCPfxYqqoigC2CygvODgVqOenH_5AQOP4'
})

const getBlogPosts = () => client.getEntries().then(response => response.items)

const getSinglePost = slug =>
  client
    .getEntries({
      'fields.slug': slug,
      content_type: 'blog'
    })
    .then(response => response.items)

export { getBlogPosts, getSinglePost }
